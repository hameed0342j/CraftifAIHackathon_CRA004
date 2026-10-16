#include "ll_net.h"

#include <string.h>
#include <time.h>

#include "esp_event.h"
#include "esp_log.h"
#include "esp_netif.h"
#include "esp_netif_sntp.h"
#include "esp_wifi.h"
#include "mqtt_client.h"
#include "sdkconfig.h"
#ifdef CONFIG_LL_TARGET_QEMU
#include "esp_eth.h"
#include "esp_eth_mac_openeth.h"
#endif

static const char *TAG = "ll_net";

static esp_mqtt_client_handle_t s_mqtt;
static ll_net_rx_cb s_on_rx;
static ll_net_conn_cb s_on_conn;

static void wifi_event(void *arg, esp_event_base_t base, int32_t id, void *data)
{
    if (base == WIFI_EVENT && id == WIFI_EVENT_STA_START) {
        esp_wifi_connect();
    } else if (base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED) {
        ESP_LOGW(TAG, "Wi-Fi lost, reconnecting");
        esp_wifi_connect();
    } else if (base == IP_EVENT && (id == IP_EVENT_STA_GOT_IP || id == IP_EVENT_ETH_GOT_IP)) {
        const ip_event_got_ip_t *ev = (const ip_event_got_ip_t *)data;
        ESP_LOGI(TAG, "got ip " IPSTR, IP2STR(&ev->ip_info.ip));
    }
}

#ifdef CONFIG_LL_TARGET_QEMU
/* QEMU has no Wi-Fi radio: use the emulated OpenCores Ethernet MAC (DP83848 PHY model). */
static void start_link(void)
{
    esp_netif_config_t ncfg = ESP_NETIF_DEFAULT_ETH();
    esp_netif_t *netif = esp_netif_new(&ncfg);
    eth_mac_config_t mac_cfg = ETH_MAC_DEFAULT_CONFIG();
    eth_phy_config_t phy_cfg = ETH_PHY_DEFAULT_CONFIG();
    phy_cfg.autonego_timeout_ms = 100;
    esp_eth_mac_t *mac = esp_eth_mac_new_openeth(&mac_cfg);
    esp_eth_phy_t *phy = esp_eth_phy_new_dp83848(&phy_cfg);
    esp_eth_config_t cfg = ETH_DEFAULT_CONFIG(mac, phy);
    esp_eth_handle_t eth = NULL;
    ESP_ERROR_CHECK(esp_eth_driver_install(&cfg, &eth));
    ESP_ERROR_CHECK(esp_netif_attach(netif, esp_eth_new_netif_glue(eth)));
    ESP_ERROR_CHECK(esp_event_handler_register(IP_EVENT, IP_EVENT_ETH_GOT_IP, wifi_event, NULL));
    ESP_ERROR_CHECK(esp_eth_start(eth));
    ESP_LOGW(TAG, "QEMU build: emulated Ethernet instead of Wi-Fi");
}
#else
static void start_link(void)
{
    esp_netif_create_default_wifi_sta();
    wifi_init_config_t wcfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&wcfg));
    ESP_ERROR_CHECK(esp_event_handler_register(WIFI_EVENT, ESP_EVENT_ANY_ID, wifi_event, NULL));
    ESP_ERROR_CHECK(esp_event_handler_register(IP_EVENT, IP_EVENT_STA_GOT_IP, wifi_event, NULL));
    wifi_config_t sta = {0};
    strlcpy((char *)sta.sta.ssid, CONFIG_LL_WIFI_SSID, sizeof sta.sta.ssid);
    strlcpy((char *)sta.sta.password, CONFIG_LL_WIFI_PASSWORD, sizeof sta.sta.password);
    sta.sta.threshold.authmode = strlen(CONFIG_LL_WIFI_PASSWORD) ? WIFI_AUTH_WPA2_PSK : WIFI_AUTH_OPEN;
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &sta));
    ESP_ERROR_CHECK(esp_wifi_start());
}
#endif

static void mqtt_event(void *arg, esp_event_base_t base, int32_t id, void *data)
{
    esp_mqtt_event_handle_t ev = (esp_mqtt_event_handle_t)data;
    switch ((esp_mqtt_event_id_t)id) {
    case MQTT_EVENT_CONNECTED:
        ESP_LOGI(TAG, "MQTT connected");
        if (s_on_conn) {
            s_on_conn(true);
        }
        break;
    case MQTT_EVENT_DISCONNECTED:
        ESP_LOGW(TAG, "MQTT disconnected");
        if (s_on_conn) {
            s_on_conn(false);
        }
        break;
    case MQTT_EVENT_DATA:
        /* our messages are < 1 KB; ignore anything fragmented across buffers */
        if (ev->current_data_offset == 0 && ev->data_len == ev->total_data_len && s_on_rx) {
            s_on_rx(ev->topic, ev->topic_len, ev->data, ev->data_len);
        }
        break;
    case MQTT_EVENT_ERROR:
        ESP_LOGE(TAG, "MQTT error");
        break;
    default:
        break;
    }
}

esp_err_t ll_net_start(ll_net_rx_cb on_rx, ll_net_conn_cb on_conn, const char *will_topic, const char *will_msg)
{
    s_on_rx = on_rx;
    s_on_conn = on_conn;

    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    start_link();

    esp_sntp_config_t scfg = ESP_NETIF_SNTP_DEFAULT_CONFIG(CONFIG_LL_SNTP_SERVER);
    esp_netif_sntp_init(&scfg);

    esp_mqtt_client_config_t mcfg = {
        .broker.address.uri = CONFIG_LL_MQTT_URI,
        .session.last_will =
            {
                .topic = will_topic,
                .msg = will_msg,
                .msg_len = (int)strlen(will_msg),
                .qos = 1,
                .retain = 1,
            },
        .session.keepalive = 15,
        .network.reconnect_timeout_ms = 3000,
        .buffer.size = 2048,
    };
    if (strlen(CONFIG_LL_MQTT_USERNAME)) {
        mcfg.credentials.username = CONFIG_LL_MQTT_USERNAME;
        mcfg.credentials.authentication.password = CONFIG_LL_MQTT_PASSWORD;
    }
    s_mqtt = esp_mqtt_client_init(&mcfg);
    if (!s_mqtt) {
        return ESP_FAIL;
    }
    ESP_ERROR_CHECK(esp_mqtt_client_register_event(s_mqtt, ESP_EVENT_ANY_ID, mqtt_event, NULL));
    return esp_mqtt_client_start(s_mqtt);
}

bool ll_net_subscribe(const char *topic_filter, int qos)
{
    return s_mqtt && esp_mqtt_client_subscribe(s_mqtt, topic_filter, qos) >= 0;
}

bool ll_net_publish(const char *topic, const char *payload, int qos, bool retain)
{
    if (!s_mqtt) {
        return false;
    }
    return esp_mqtt_client_enqueue(s_mqtt, topic, payload, (int)strlen(payload), qos, retain, true) >= 0;
}

bool ll_net_time_valid(void)
{
    return time(NULL) > 1700000000; /* SNTP has synced */
}
