/* Virtual I/O for QEMU builds: same API as ll_hw.c, but the servo, limit switch and
 * wetness probe are MQTT messages exchanged with the simulator's physics. Everything
 * above this file (state machine, tasks, NVS, MQTT, JSON) is the production code. */
#include "ll_hw.h"

#ifdef CONFIG_LL_TARGET_QEMU

#include <stdio.h>
#include <string.h>

#include "cJSON.h"
#include "esp_log.h"
#include "ll_net.h"

static const char *TAG = "ll_hw_sim";

#define WET_AVG 8

static char s_pins_topic[128];
static char s_out_topic[128];
static volatile bool s_limit;
static volatile int s_wet_raw = 3000;
static int s_servo_deg = CONFIG_LL_SERVO_OPEN_DEG;
static bool s_alarm;
static int s_wet_buf[WET_AVG];
static int s_wet_n, s_wet_i;
static bool s_wet;

static void publish_outputs(void)
{
    char buf[64];
    snprintf(buf, sizeof buf, "{\"servo_deg\":%d,\"alarm\":%s}", s_servo_deg, s_alarm ? "true" : "false");
    ll_net_publish(s_out_topic, buf, 1, true); /* retained: the world always sees the latest command */
}

esp_err_t ll_hw_init(void)
{
    ESP_LOGW(TAG, "QEMU build: servo, limit switch and wetness probe are virtual pins over MQTT");
    return ESP_OK;
}

void ll_hw_sim_set_topics(const char *pins_topic, const char *outputs_topic)
{
    strlcpy(s_pins_topic, pins_topic, sizeof s_pins_topic);
    strlcpy(s_out_topic, outputs_topic, sizeof s_out_topic);
}

void ll_hw_sim_on_connect(void)
{
    ll_net_subscribe(s_pins_topic, 0);
    publish_outputs();
}

bool ll_hw_sim_ingest(const char *topic, int topic_len, const char *data, int data_len)
{
    if (topic_len != (int)strlen(s_pins_topic) || memcmp(topic, s_pins_topic, (size_t)topic_len) != 0) {
        return false;
    }
    cJSON *root = cJSON_ParseWithLength(data, (size_t)data_len);
    if (root) {
        const cJSON *lim = cJSON_GetObjectItemCaseSensitive(root, "limit");
        const cJSON *wet = cJSON_GetObjectItemCaseSensitive(root, "wet_raw");
        if (cJSON_IsBool(lim)) {
            s_limit = cJSON_IsTrue(lim);
        }
        if (cJSON_IsNumber(wet)) {
            s_wet_raw = wet->valueint;
        }
        cJSON_Delete(root);
    }
    return true;
}

void ll_valve_command(bool close, uint32_t now_ms)
{
    (void)now_ms;
    s_servo_deg = close ? CONFIG_LL_SERVO_CLOSED_DEG : CONFIG_LL_SERVO_OPEN_DEG;
    ESP_LOGI(TAG, "valve -> %s (%d deg)", close ? "CLOSE" : "OPEN", s_servo_deg);
    publish_outputs();
}

void ll_valve_service(uint32_t now_ms) { (void)now_ms; }

bool ll_limit_poll(void) { return s_limit; }

int ll_wet_sample(void)
{
    s_wet_buf[s_wet_i] = s_wet_raw;
    s_wet_i = (s_wet_i + 1) % WET_AVG;
    if (s_wet_n < WET_AVG) {
        s_wet_n++;
    }
    int sum = 0;
    for (int i = 0; i < s_wet_n; i++) {
        sum += s_wet_buf[i];
    }
    return sum / s_wet_n;
}

bool ll_wet_classify(int avg_raw)
{
#ifdef CONFIG_LL_WET_ACTIVE_LOW
    if (!s_wet && avg_raw <= CONFIG_LL_WET_ON_RAW) {
        s_wet = true;
    } else if (s_wet && avg_raw >= CONFIG_LL_WET_OFF_RAW) {
        s_wet = false;
    }
#else
    if (!s_wet && avg_raw >= CONFIG_LL_WET_ON_RAW) {
        s_wet = true;
    } else if (s_wet && avg_raw <= CONFIG_LL_WET_OFF_RAW) {
        s_wet = false;
    }
#endif
    return s_wet;
}

void ll_alarm_set(bool on)
{
    if (on != s_alarm) {
        s_alarm = on;
        ESP_LOGW(TAG, "alarm %s", on ? "ON" : "off");
        publish_outputs();
    }
}

#endif /* CONFIG_LL_TARGET_QEMU */
