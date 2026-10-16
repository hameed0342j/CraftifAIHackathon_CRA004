/* JSON codec for the contracts in /contracts (leak_event, command, device_state, receipt). */
#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "ll_fsm.h"

typedef struct {
    char event_id[LL_ID_MAX];
    char incident_id[LL_ID_MAX];
    char zone_id[LL_ZONE_MAX];
    int kind; /* ll_kind_t */
    float confidence;
    float pool_area;
    float growth_rate;
} ll_vision_msg_t;

/* false = malformed (wrong schema, missing/oversized fields). */
bool ll_msg_parse_event(const char *data, int len, ll_vision_msg_t *out);
bool ll_msg_parse_command(const char *data, int len, int *cmd);

/* Return malloc'd JSON strings; free() them. NULL on allocation failure. */
char *ll_msg_state_json(const ll_fsm_t *f, bool online, int wetness_raw, uint32_t uptime_ms, const char *fw);
char *ll_msg_offline_json(const char *zone_id);
char *ll_msg_receipt_json(const char *zone_id, const ll_transition_t *t, int wetness_raw);

/* "2026-10-16T12:00:00.123Z", or "" before SNTP sync. */
void ll_msg_iso_now(char *buf, size_t n);
