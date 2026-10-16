#include "ll_msg.h"

#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/time.h>
#include <time.h>

#include "cJSON.h"

#define SCHEMA_EVENT "leaklatch/leak_event/v1"
#define SCHEMA_CMD "leaklatch/command/v1"
#define SCHEMA_STATE "leaklatch/device_state/v1"
#define SCHEMA_RECEIPT "leaklatch/receipt/v1"

/* copy a JSON string field; false if missing, not a string, or too long to keep exactly */
static bool get_str(const cJSON *obj, const char *key, char *dst, size_t cap, bool required)
{
    const cJSON *it = cJSON_GetObjectItemCaseSensitive(obj, key);
    if (!cJSON_IsString(it) || !it->valuestring) {
        dst[0] = '\0';
        return !required;
    }
    size_t n = strlen(it->valuestring);
    if (n >= cap) {
        return false;
    }
    memcpy(dst, it->valuestring, n + 1);
    return true;
}

static bool get_num(const cJSON *obj, const char *key, float *out)
{
    const cJSON *it = cJSON_GetObjectItemCaseSensitive(obj, key);
    if (!cJSON_IsNumber(it) || !isfinite(it->valuedouble)) {
        return false;
    }
    *out = (float)it->valuedouble;
    return true;
}

static bool schema_ok(const cJSON *obj, const char *expected)
{
    const cJSON *it = cJSON_GetObjectItemCaseSensitive(obj, "schema");
    return cJSON_IsString(it) && strcmp(it->valuestring, expected) == 0;
}

bool ll_msg_parse_event(const char *data, int len, ll_vision_msg_t *out)
{
    memset(out, 0, sizeof *out);
    cJSON *root = cJSON_ParseWithLength(data, (size_t)len);
    if (!root) {
        return false;
    }
    char kind[8] = "";
    bool ok = cJSON_IsObject(root) && schema_ok(root, SCHEMA_EVENT) &&
              get_str(root, "event_id", out->event_id, sizeof out->event_id, true) &&
              get_str(root, "incident_id", out->incident_id, sizeof out->incident_id, true) &&
              get_str(root, "zone_id", out->zone_id, sizeof out->zone_id, true) &&
              get_str(root, "kind", kind, sizeof kind, true) && get_num(root, "confidence", &out->confidence) &&
              get_num(root, "pool_area", &out->pool_area) && get_num(root, "growth_rate", &out->growth_rate);
    if (ok) {
        if (strcmp(kind, "detect") == 0) {
            out->kind = LL_KIND_DETECT;
        } else if (strcmp(kind, "update") == 0) {
            out->kind = LL_KIND_UPDATE;
        } else if (strcmp(kind, "clear") == 0) {
            out->kind = LL_KIND_CLEAR;
        } else {
            ok = false;
        }
    }
    cJSON_Delete(root);
    return ok;
}

bool ll_msg_parse_command(const char *data, int len, int *cmd)
{
    cJSON *root = cJSON_ParseWithLength(data, (size_t)len);
    if (!root) {
        return false;
    }
    char c[8] = "";
    bool ok = cJSON_IsObject(root) && schema_ok(root, SCHEMA_CMD) && get_str(root, "cmd", c, sizeof c, true);
    if (ok) {
        if (strcmp(c, "reset") == 0) {
            *cmd = LL_CMD_RESET;
        } else if (strcmp(c, "close") == 0) {
            *cmd = LL_CMD_CLOSE;
        } else {
            ok = false;
        }
    }
    cJSON_Delete(root);
    return ok;
}

static double r4(float v) { return round((double)v * 10000.0) / 10000.0; }

void ll_msg_iso_now(char *buf, size_t n)
{
    struct timeval tv;
    gettimeofday(&tv, NULL);
    if (tv.tv_sec < 1700000000) {
        buf[0] = '\0';
        return;
    }
    struct tm tm;
    gmtime_r(&tv.tv_sec, &tm);
    size_t w = strftime(buf, n, "%Y-%m-%dT%H:%M:%S", &tm);
    snprintf(buf + w, n - w, ".%03dZ", (int)(tv.tv_usec / 1000));
}

static void add_timestamp(cJSON *o)
{
    char ts[32];
    ll_msg_iso_now(ts, sizeof ts);
    if (ts[0]) {
        cJSON_AddStringToObject(o, "timestamp", ts);
    }
}

static char *finish(cJSON *o)
{
    char *s = cJSON_PrintUnformatted(o);
    cJSON_Delete(o);
    return s;
}

char *ll_msg_state_json(const ll_fsm_t *f, bool online, int wetness_raw, uint32_t uptime_ms, const char *fw)
{
    cJSON *o = cJSON_CreateObject();
    if (!o) {
        return NULL;
    }
    ll_state_t st = ll_fsm_state(f);
    cJSON_AddStringToObject(o, "schema", SCHEMA_STATE);
    cJSON_AddStringToObject(o, "zone_id", f->zone_id);
    cJSON_AddBoolToObject(o, "online", online);
    cJSON_AddStringToObject(o, "state", ll_state_name(st));
    cJSON_AddStringToObject(o, "reason", ll_fsm_reason(f));
    cJSON_AddStringToObject(o, "valve", ll_state_valve_closed(st) ? "closed" : "open");
    cJSON_AddBoolToObject(o, "limit_switch", f->limit_closed);
    cJSON_AddBoolToObject(o, "wet", f->wet);
    cJSON_AddNumberToObject(o, "wetness_raw", wetness_raw);
    cJSON_AddStringToObject(o, "incident_event_id", ll_fsm_trigger_event_id(f));
    cJSON_AddNumberToObject(o, "uptime_ms", uptime_ms);
    add_timestamp(o);
    cJSON_AddStringToObject(o, "fw", fw);
    cJSON *c = cJSON_AddObjectToObject(o, "counters");
    cJSON_AddNumberToObject(c, "accepted", ll_fsm_counter(f, 0));
    cJSON_AddNumberToObject(c, "zone_mismatch", ll_fsm_counter(f, 1));
    cJSON_AddNumberToObject(c, "duplicate", ll_fsm_counter(f, 2));
    cJSON_AddNumberToObject(c, "rejected", ll_fsm_counter(f, 3));
    return finish(o);
}

char *ll_msg_offline_json(const char *zone_id)
{
    cJSON *o = cJSON_CreateObject();
    if (!o) {
        return NULL;
    }
    cJSON_AddStringToObject(o, "schema", SCHEMA_STATE);
    cJSON_AddStringToObject(o, "zone_id", zone_id);
    cJSON_AddBoolToObject(o, "online", false);
    return finish(o);
}

char *ll_msg_receipt_json(const char *zone_id, const ll_transition_t *t, int wetness_raw)
{
    cJSON *o = cJSON_CreateObject();
    if (!o) {
        return NULL;
    }
    cJSON_AddStringToObject(o, "schema", SCHEMA_RECEIPT);
    cJSON_AddStringToObject(o, "zone_id", zone_id);
    cJSON_AddNumberToObject(o, "seq", t->seq);
    cJSON_AddStringToObject(o, "from", ll_state_name((ll_state_t)t->from));
    cJSON_AddStringToObject(o, "to", ll_state_name((ll_state_t)t->to));
    cJSON_AddStringToObject(o, "reason", t->reason);
    cJSON_AddStringToObject(o, "trigger_event_id", t->trigger_event_id);
    cJSON_AddStringToObject(o, "last_event_id", t->last_event_id);
    cJSON_AddNumberToObject(o, "uptime_ms", t->t_ms);
    add_timestamp(o);
    cJSON *e = cJSON_AddObjectToObject(o, "evidence");
    cJSON_AddNumberToObject(e, "confidence", r4(t->confidence));
    cJSON_AddNumberToObject(e, "pool_area", r4(t->pool_area));
    cJSON_AddNumberToObject(e, "growth_rate", r4(t->growth_rate));
    cJSON_AddBoolToObject(e, "wet", t->wet);
    cJSON_AddNumberToObject(e, "wetness_raw", wetness_raw);
    cJSON_AddBoolToObject(e, "limit_switch", t->limit_switch);
    cJSON *v = cJSON_AddObjectToObject(o, "verification");
    cJSON_AddBoolToObject(v, "mechanical", t->mech_verified);
    cJSON_AddNumberToObject(v, "mechanical_ms", t->mech_verified_after_ms);
    cJSON_AddBoolToObject(v, "hydraulic", t->hydro_verified);
    cJSON_AddNumberToObject(v, "growth_after_close", r4(t->growth_after_close));
    cJSON_AddNumberToObject(v, "close_attempts", t->close_attempts);
    return finish(o);
}
