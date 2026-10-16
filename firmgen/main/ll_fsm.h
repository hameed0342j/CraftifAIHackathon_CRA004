/*
 * LeakLatch zone-locked evidence-to-action state machine.
 *
 * Pure C99, no ESP-IDF or libc allocation: the same file runs on the ESP32
 * (firmgen/main), in the host unit tests (firmgen/test) and inside the
 * closed-loop simulator via ctypes (simlab/fsm_native.py).
 *
 *   IDLE -> SUSPECT -> CONFIRMING -> CLOSED -> VERIFYING -> LATCHED
 *                                                     \-> FAULT
 *
 * Inputs are pushed in with an explicit monotonic millisecond clock; outputs
 * are a bitmask of actions the caller must execute (move the valve, publish).
 * All time math is unsigned and wrap-safe.
 */
#ifndef LL_FSM_H
#define LL_FSM_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#if defined(_WIN32) && defined(LL_BUILD_SHARED)
#define LL_API __declspec(dllexport)
#else
#define LL_API
#endif

#define LL_ID_MAX 40     /* event ids are 32 hex chars + NUL; leave headroom */
#define LL_ZONE_MAX 24
#define LL_REASON_MAX 32
#define LL_SEEN_IDS 16   /* de-duplication ring */

typedef enum {
    LL_ST_IDLE = 0,
    LL_ST_SUSPECT,
    LL_ST_CONFIRMING,
    LL_ST_CLOSED,
    LL_ST_VERIFYING,
    LL_ST_LATCHED,
    LL_ST_FAULT,
    LL_ST__COUNT
} ll_state_t;

typedef enum { LL_KIND_DETECT = 0, LL_KIND_UPDATE = 1, LL_KIND_CLEAR = 2 } ll_kind_t;

typedef enum { LL_CMD_RESET = 0, LL_CMD_CLOSE = 1 } ll_cmd_t;

typedef enum {
    LL_EV_ACCEPTED = 0,
    LL_EV_ZONE_MISMATCH,
    LL_EV_DUPLICATE,
    LL_EV_LOW_CONFIDENCE,
    LL_EV_TOO_SMALL,
    LL_EV_MALFORMED,
} ll_verdict_t;

/* Action bits returned by ll_fsm_take_actions(). */
#define LL_ACT_VALVE_CLOSE (1u << 0)
#define LL_ACT_VALVE_OPEN (1u << 1)
#define LL_ACT_PUBLISH_STATE (1u << 2)
#define LL_ACT_RECEIPT (1u << 3)   /* a transition happened: publish a receipt */
#define LL_ACT_ALARM_ON (1u << 4)
#define LL_ACT_ALARM_OFF (1u << 5)
#define LL_ACT_PERSIST (1u << 6)   /* store ll_fsm_state() in non-volatile memory */

/* Every field is 4 bytes so the ctypes mirror in simlab stays trivial. */
typedef struct {
    float min_confidence;         /* vision events below this are rejected */
    float min_pool_area_m2;       /* ... and so are pools smaller than this */
    float growth_close_min;       /* m2/min; do not close on a pool that is clearly shrinking */
    float growth_stop_max;        /* m2/min; at or below this the pool has stopped growing */
    uint32_t suspect_timeout_ms;  /* vision evidence with no local wetness -> back to IDLE */
    uint32_t confirm_hold_ms;     /* local wetness must persist this long */
    uint32_t vision_fresh_ms;     /* a vision event older than this is stale */
    uint32_t confirm_timeout_ms;  /* give up confirming after this long */
    uint32_t travel_ms;           /* servo travel time before we start verifying */
    uint32_t close_timeout_ms;    /* limit switch must engage within this after a close command */
    uint32_t close_retries;       /* extra close attempts before FAULT */
    uint32_t verify_window_ms;    /* hydraulic verification window after closing */
    uint32_t verify_stop_hold_ms; /* pool growth must stay stopped this long */
    uint32_t failsafe_wet_ms;     /* local wetness alone closes after this long (0 = off) */
    float vision_only_area_m2;    /* vision-only override: pool at least this big (0 = off) */
    float vision_only_growth;     /* ... and growing at least this fast (m2/min) */
    uint32_t vision_only_hold_ms; /* ... for this long, without local wetness */
    float rearm_area_factor;      /* an acknowledged incident re-opens only if its pool grows */
    float rearm_area_min_m2;      /* to factor x the acknowledged area AND by at least this much */
} ll_config_t;

/* One state transition with the evidence that caused it: the payload of a
 * receipt. Every field is 4-byte sized (bools as uint32_t) for ctypes. */
typedef struct {
    uint32_t seq;
    uint32_t from; /* ll_state_t */
    uint32_t to;   /* ll_state_t */
    uint32_t t_ms;
    float confidence;
    float pool_area;
    float growth_rate;
    uint32_t wet;
    uint32_t limit_switch;
    uint32_t mech_verified;
    uint32_t mech_verified_after_ms;
    uint32_t hydro_verified;
    uint32_t close_attempts;
    float growth_after_close;
    char reason[LL_REASON_MAX];
    char trigger_event_id[LL_ID_MAX];
    char last_event_id[LL_ID_MAX];
} ll_transition_t;

#define LL_LOG_LEN 8

typedef struct {
    ll_config_t cfg;
    char zone_id[LL_ZONE_MAX];

    ll_state_t state;
    ll_state_t prev_state;
    uint32_t state_since_ms;
    uint32_t seq; /* transition counter */
    char reason[LL_REASON_MAX];

    /* evidence of the active incident */
    char incident_id[LL_ID_MAX];
    char trigger_event_id[LL_ID_MAX];
    char last_event_id[LL_ID_MAX];
    bool have_vision;
    uint32_t last_vision_ms;
    ll_kind_t last_kind;
    float last_conf, last_area, last_growth;

    /* local sensors */
    bool wet;
    uint32_t wet_since_ms;
    bool limit_closed;

    /* actuation and verification */
    uint32_t closed_at_ms;   /* first close command of this incident */
    uint32_t close_cmd_ms;   /* latest close command */
    uint32_t close_attempts;
    bool mech_verified;
    uint32_t mech_verified_after_ms;
    bool hydro_verified;
    bool stop_tracking;
    uint32_t stop_since_ms;
    bool vision_after_close;
    float growth_after_close;
    bool vision_only_tracking;
    uint32_t vision_only_since_ms;
    bool restore_check; /* restored after a reboot: the limit switch must re-prove closure */

    /* the last incident that went back to IDLE (dismissed or reset by the operator):
     * its residual pool must not re-trigger the valve unless it grows again */
    char ack_incident_id[LL_ID_MAX];
    float ack_area;
    bool ack_wet; /* probe was wet when acknowledged; cleared once it dries */

    /* de-duplication and counters */
    char seen[LL_SEEN_IDS][LL_ID_MAX];
    uint32_t seen_next;
    uint32_t n_accepted, n_zone_mismatch, n_duplicate, n_rejected;

    /* transitions not yet turned into receipts (oldest dropped on overflow) */
    ll_transition_t log[LL_LOG_LEN];
    uint32_t log_head, log_count;

    uint32_t actions; /* pending action bits */
} ll_fsm_t;

LL_API void ll_config_default(ll_config_t *cfg);
LL_API void ll_fsm_init(ll_fsm_t *f, const ll_config_t *cfg, const char *zone_id, uint32_t now_ms);
/* Call once after init with the state read back from NVS. A valve that was
 * closed before a reboot stays closed (LATCHED, or FAULT if it was faulted). */
LL_API void ll_fsm_restore(ll_fsm_t *f, ll_state_t persisted, uint32_t now_ms);

/* incident_id may be NULL or "" (then event_id is used). */
LL_API ll_verdict_t ll_fsm_on_vision(ll_fsm_t *f, const char *event_id, const char *incident_id,
                                     const char *zone_id, int kind, float confidence, float pool_area_m2,
                                     float growth_m2_min, uint32_t now_ms);
LL_API void ll_fsm_on_wetness(ll_fsm_t *f, bool wet, uint32_t now_ms);
LL_API void ll_fsm_on_limit(ll_fsm_t *f, bool closed, uint32_t now_ms);
LL_API void ll_fsm_on_command(ll_fsm_t *f, int cmd, uint32_t now_ms);
LL_API void ll_fsm_tick(ll_fsm_t *f, uint32_t now_ms);
LL_API uint32_t ll_fsm_take_actions(ll_fsm_t *f);
/* Pops the oldest pending transition; returns false when none is left. */
LL_API bool ll_fsm_pop_transition(ll_fsm_t *f, ll_transition_t *out);

LL_API ll_state_t ll_fsm_state(const ll_fsm_t *f);
LL_API ll_state_t ll_fsm_prev_state(const ll_fsm_t *f);
LL_API uint32_t ll_fsm_seq(const ll_fsm_t *f);
LL_API const char *ll_fsm_reason(const ll_fsm_t *f);
LL_API const char *ll_fsm_trigger_event_id(const ll_fsm_t *f);
LL_API const char *ll_fsm_incident_id(const ll_fsm_t *f);
LL_API const char *ll_fsm_last_event_id(const ll_fsm_t *f);
LL_API bool ll_state_valve_closed(ll_state_t s);
LL_API const char *ll_state_name(ll_state_t s);
LL_API const char *ll_verdict_name(ll_verdict_t v);
LL_API uint32_t ll_fsm_counter(const ll_fsm_t *f, int which); /* 0 accepted, 1 zone_mismatch, 2 duplicate, 3 rejected */
LL_API size_t ll_fsm_sizeof(void);
LL_API size_t ll_config_sizeof(void);
LL_API size_t ll_transition_sizeof(void);

#ifdef __cplusplus
}
#endif
#endif /* LL_FSM_H */
