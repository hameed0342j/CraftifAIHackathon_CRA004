/*
 * LeakLatch FirmGen: zone-locked valve node.
 *
 * One control task owns the state machine (ll_fsm.c). The MQTT task only parses
 * messages and queues them; sensors are polled by the control task. Every
 * transition is persisted to NVS and published as a receipt, so the chain
 * vision event -> valve action -> verification can be audited end to end.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "esp_app_desc.h"
#include "esp_log.h"
#include "esp_task_wdt.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"
#include "sdkconfig.h"

#include "ll_fsm.h"
#include "ll_hw.h"
#include "ll_msg.h"
#include "ll_net.h"
#include "ll_store.h"

static const char *TAG = "leaklatch";

#define CONTROL_PERIOD_MS 20
#define WET_PERIOD_MS 200
#define STATE_HEARTBEAT_MS 30000

typedef enum { IN_VISION, IN_COMMAND, IN_NET } in_type_t;

typedef struct {
    in_type_t type;
    union {
        ll_vision_msg_t vision;
        int command;
        bool connected;
    };
} ll_input_t;

static QueueHandle_t s_inputs;
static ll_fsm_t s_fsm; /* owned by the control task */
static char s_topic_state[128], s_topic_receipt[128], s_topic_cmd[128], s_topic_events[128];
static volatile bool s_online;
static volatile uint32_t s_dropped;
static int s_wet_raw = -1;

static uint32_t now_ms(void) { return (uint32_t)(esp_timer_get_time() / 1000ULL); }

/* topic is <prefix>/<site>/zone/<zone>/event: the payload must name the same zone */
static bool topic_zone_is(const char *topic, int tlen, const char *zone)
{
    static const char marker[] = "/zone/";
    for (int i = 0; i + (int)sizeof marker - 1 <= tlen; i++) {
        if (memcmp(topic + i, marker, sizeof marker - 1) == 0) {
            const char *z = topic + i + sizeof marker - 1;
            int zl = 0;
            while (z + zl < topic + tlen && z[zl] != '/') {
                zl++;
            }
            return zl == (int)strlen(zone) && memcmp(z, zone, (size_t)zl) == 0;
        }
    }
    return false;
}

static void on_mqtt_rx(const char *topic, int tlen, const char *data, int dlen)
{
#ifdef CONFIG_LL_TARGET_QEMU
    if (ll_hw_sim_ingest(topic, tlen, data, dlen)) {
        return; /* virtual pins, not a leak event */
    }
#endif
    ll_input_t in = {0};
    if (tlen == (int)strlen(s_topic_cmd) && memcmp(topic, s_topic_cmd, (size_t)tlen) == 0) {
        if (!ll_msg_parse_command(data, dlen, &in.command)) {
            ESP_LOGW(TAG, "malformed command ignored");
            return;
        }
        in.type = IN_COMMAND;
    } else {
        in.type = IN_VISION;
        if (!ll_msg_parse_event(data, dlen, &in.vision) || !topic_zone_is(topic, tlen, in.vision.zone_id)) {
            in.vision.event_id[0] = '\0'; /* the FSM counts it as malformed */
        }
    }
    if (xQueueSend(s_inputs, &in, 0) != pdTRUE) {
        s_dropped++;
    }
}

static void on_mqtt_conn(bool connected)
{
    s_online = connected;
    if (connected) {
        ll_net_subscribe(s_topic_events, 1); /* all zones: the zone lock is enforced in the FSM */
        ll_net_subscribe(s_topic_cmd, 1);
#ifdef CONFIG_LL_TARGET_QEMU
        ll_hw_sim_on_connect();
#endif
    }
    ll_input_t in = {.type = IN_NET, .connected = connected};
    xQueueSend(s_inputs, &in, 0);
}

static void publish_state(void)
{
    char *js = ll_msg_state_json(&s_fsm, true, s_wet_raw, now_ms(), esp_app_get_description()->version);
    if (js) {
        ll_net_publish(s_topic_state, js, 1, true);
        free(js);
    }
}

static void publish_receipts(void)
{
    ll_transition_t tr;
    while (ll_fsm_pop_transition(&s_fsm, &tr)) {
        ESP_LOGI(TAG, "#%lu %s -> %s (%s) trigger=%s", (unsigned long)tr.seq, ll_state_name((ll_state_t)tr.from),
                 ll_state_name((ll_state_t)tr.to), tr.reason, tr.trigger_event_id);
        char *js = ll_msg_receipt_json(s_fsm.zone_id, &tr, s_wet_raw);
        if (js) {
            ll_net_publish(s_topic_receipt, js, 1, false);
            free(js);
        }
    }
}

static void apply_actions(uint32_t a, uint32_t now)
{
    if (a & LL_ACT_VALVE_CLOSE) {
        ll_valve_command(true, now);
    }
    if (a & LL_ACT_VALVE_OPEN) {
        ll_valve_command(false, now);
    }
    if (a & LL_ACT_ALARM_ON) {
        ll_alarm_set(true);
    }
    if (a & LL_ACT_ALARM_OFF) {
        ll_alarm_set(false);
    }
    if (a & LL_ACT_PERSIST) {
        ll_store_save_state(ll_fsm_state(&s_fsm));
    }
    if (a & LL_ACT_RECEIPT) {
        publish_receipts();
    }
    if (a & LL_ACT_PUBLISH_STATE) {
        publish_state();
    }
}

static void handle_input(const ll_input_t *in, uint32_t now, bool *force_state)
{
    switch (in->type) {
    case IN_VISION: {
        const ll_vision_msg_t *v = &in->vision;
        ll_verdict_t verdict = ll_fsm_on_vision(&s_fsm, v->event_id, v->incident_id, v->zone_id, v->kind,
                                                v->confidence, v->pool_area, v->growth_rate, now);
        ESP_LOGI(TAG, "event %.8s zone=%s kind=%d conf=%.2f area=%.3f growth=%.3f -> %s", v->event_id, v->zone_id,
                 v->kind, v->confidence, v->pool_area, v->growth_rate, ll_verdict_name(verdict));
        break;
    }
    case IN_COMMAND:
        ESP_LOGW(TAG, "operator command %s", in->command == LL_CMD_RESET ? "reset" : "close");
        ll_fsm_on_command(&s_fsm, in->command, now);
        break;
    case IN_NET:
        *force_state = in->connected;
        break;
    }
}

static void control_task(void *arg)
{
    (void)arg;
    ESP_ERROR_CHECK(esp_task_wdt_add(NULL));
    uint32_t last_wet = 0, last_state = 0;
    bool force_state = false; /* set when MQTT connects */
    for (;;) {
        ll_input_t in;
        if (xQueueReceive(s_inputs, &in, pdMS_TO_TICKS(CONTROL_PERIOD_MS)) == pdTRUE) {
            handle_input(&in, now_ms(), &force_state);
        }
        uint32_t now = now_ms();
        ll_fsm_on_limit(&s_fsm, ll_limit_poll(), now);
        if ((uint32_t)(now - last_wet) >= WET_PERIOD_MS) {
            last_wet = now;
            s_wet_raw = ll_wet_sample();
            ll_fsm_on_wetness(&s_fsm, ll_wet_classify(s_wet_raw), now);
        }
        ll_fsm_tick(&s_fsm, now);
        ll_valve_service(now);

        uint32_t a = ll_fsm_take_actions(&s_fsm);
        if (force_state) {
            /* (re)connected: flush receipts recorded while offline, e.g. the boot restore */
            a |= LL_ACT_PUBLISH_STATE | LL_ACT_RECEIPT;
            force_state = false;
        } else if ((uint32_t)(now - last_state) >= STATE_HEARTBEAT_MS) {
            a |= LL_ACT_PUBLISH_STATE;
        }
        if (a & LL_ACT_PUBLISH_STATE) {
            last_state = now;
        }
        apply_actions(a, now);
        esp_task_wdt_reset();
    }
}

static void load_config(ll_config_t *cfg)
{
    ll_config_default(cfg);
    cfg->min_confidence = CONFIG_LL_MIN_CONFIDENCE_PCT / 100.0f;
    cfg->min_pool_area_m2 = CONFIG_LL_MIN_AREA_CM2 / 10000.0f;
    cfg->suspect_timeout_ms = CONFIG_LL_SUSPECT_TIMEOUT_S * 1000u;
    cfg->confirm_hold_ms = CONFIG_LL_CONFIRM_HOLD_MS;
    cfg->close_timeout_ms = CONFIG_LL_CLOSE_TIMEOUT_MS;
    cfg->verify_window_ms = CONFIG_LL_VERIFY_WINDOW_S * 1000u;
    cfg->failsafe_wet_ms = CONFIG_LL_FAILSAFE_WET_S * 1000u;
    cfg->vision_only_area_m2 = CONFIG_LL_VISION_ONLY_AREA_CM2 / 10000.0f;
}

void app_main(void)
{
    ESP_ERROR_CHECK(ll_store_init());
    ESP_ERROR_CHECK(ll_hw_init());

    const char *base_fmt = CONFIG_LL_TOPIC_PREFIX "/" CONFIG_LL_SITE_ID "/zone/";
    snprintf(s_topic_state, sizeof s_topic_state, "%s%s/state", base_fmt, CONFIG_LL_ZONE_ID);
    snprintf(s_topic_receipt, sizeof s_topic_receipt, "%s%s/receipt", base_fmt, CONFIG_LL_ZONE_ID);
    snprintf(s_topic_cmd, sizeof s_topic_cmd, "%s%s/cmd", base_fmt, CONFIG_LL_ZONE_ID);
    snprintf(s_topic_events, sizeof s_topic_events, "%s+/event", base_fmt);
#ifdef CONFIG_LL_TARGET_QEMU
    {
        static char pins[128], outputs[128];
        snprintf(pins, sizeof pins, CONFIG_LL_TOPIC_PREFIX "/" CONFIG_LL_SITE_ID "/sim/%s/pins", CONFIG_LL_ZONE_ID);
        snprintf(outputs, sizeof outputs, CONFIG_LL_TOPIC_PREFIX "/" CONFIG_LL_SITE_ID "/sim/%s/outputs",
                 CONFIG_LL_ZONE_ID);
        ll_hw_sim_set_topics(pins, outputs);
    }
#endif

    ll_config_t cfg;
    load_config(&cfg);
    uint32_t now = now_ms();
    ll_fsm_init(&s_fsm, &cfg, CONFIG_LL_ZONE_ID, now);
    int persisted = ll_store_load_state();
    if (persisted >= 0 && persisted < LL_ST__COUNT) {
        ll_fsm_restore(&s_fsm, (ll_state_t)persisted, now);
    }
    ESP_LOGI(TAG, "zone %s starts in %s (%s)", CONFIG_LL_ZONE_ID, ll_state_name(ll_fsm_state(&s_fsm)),
             ll_fsm_reason(&s_fsm));
    /* drive the valve to its boot position before the network is up; receipts wait in the FSM log */
    uint32_t boot = ll_fsm_take_actions(&s_fsm);
    apply_actions(boot & (LL_ACT_VALVE_CLOSE | LL_ACT_VALVE_OPEN | LL_ACT_ALARM_ON | LL_ACT_ALARM_OFF), now);

    s_inputs = xQueueCreate(16, sizeof(ll_input_t));
    char *will = ll_msg_offline_json(CONFIG_LL_ZONE_ID);
    ESP_ERROR_CHECK(ll_net_start(on_mqtt_rx, on_mqtt_conn, s_topic_state, will));
    /* the MQTT client copied the will message */
    free(will);

    xTaskCreatePinnedToCore(control_task, "ll_ctrl", 6144, NULL, 6, NULL, 1);
}
