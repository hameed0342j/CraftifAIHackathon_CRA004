/* LeakLatch state machine. See ll_fsm.h for the contract. */
#include "ll_fsm.h"

#include <string.h>

static const char *const k_state_names[LL_ST__COUNT] = {
    "IDLE", "SUSPECT", "CONFIRMING", "CLOSED", "VERIFYING", "LATCHED", "FAULT",
};

static const char *const k_verdict_names[] = {
    "accepted", "zone_mismatch", "duplicate", "low_confidence", "too_small", "malformed",
};

/* true once `dur` ms have passed since `since`; correct across uint32 wrap */
static bool elapsed(uint32_t now, uint32_t since, uint32_t dur)
{
    return (uint32_t)(now - since) >= dur;
}

static void copy_str(char *dst, size_t cap, const char *src)
{
    size_t i = 0;
    if (src) {
        for (; i + 1 < cap && src[i]; i++) {
            dst[i] = src[i];
        }
    }
    dst[i] = '\0';
}

void ll_config_default(ll_config_t *c)
{
    c->min_confidence = 0.60f;
    c->min_pool_area_m2 = 0.02f;
    c->growth_close_min = -0.05f;
    c->growth_stop_max = 0.02f;
    c->suspect_timeout_ms = 45000;
    c->confirm_hold_ms = 3000;
    c->vision_fresh_ms = 10000;
    c->confirm_timeout_ms = 30000;
    c->travel_ms = 1500;
    c->close_timeout_ms = 5000;
    c->close_retries = 1;
    c->verify_window_ms = 60000;
    c->verify_stop_hold_ms = 5000;
    c->failsafe_wet_ms = 180000;
    c->vision_only_area_m2 = 0.0f; /* off: a camera alone never shuts the water */
    c->vision_only_growth = 0.05f;
    c->vision_only_hold_ms = 30000;
    c->rearm_area_factor = 1.5f;
    c->rearm_area_min_m2 = 0.05f;
}

bool ll_state_valve_closed(ll_state_t s)
{
    return s == LL_ST_CLOSED || s == LL_ST_VERIFYING || s == LL_ST_LATCHED || s == LL_ST_FAULT;
}

static void log_transition(ll_fsm_t *f, ll_state_t from, ll_state_t to, uint32_t now)
{
    uint32_t slot;
    if (f->log_count == LL_LOG_LEN) { /* drop the oldest */
        f->log_head = (f->log_head + 1) % LL_LOG_LEN;
        f->log_count--;
    }
    slot = (f->log_head + f->log_count) % LL_LOG_LEN;
    ll_transition_t *t = &f->log[slot];
    t->seq = f->seq;
    t->from = (uint32_t)from;
    t->to = (uint32_t)to;
    t->t_ms = now;
    t->confidence = f->last_conf;
    t->pool_area = f->last_area;
    t->growth_rate = f->last_growth;
    t->wet = f->wet;
    t->limit_switch = f->limit_closed;
    t->mech_verified = f->mech_verified;
    t->mech_verified_after_ms = f->mech_verified_after_ms;
    t->hydro_verified = f->hydro_verified;
    t->close_attempts = f->close_attempts;
    t->growth_after_close = f->growth_after_close;
    copy_str(t->reason, sizeof t->reason, f->reason);
    copy_str(t->trigger_event_id, sizeof t->trigger_event_id, f->trigger_event_id);
    copy_str(t->last_event_id, sizeof t->last_event_id, f->last_event_id);
    f->log_count++;
}

static void enter(ll_fsm_t *f, ll_state_t to, const char *reason, uint32_t now)
{
    ll_state_t from = f->state;
    bool was_closed = ll_state_valve_closed(from);

    f->prev_state = from;
    f->state = to;
    f->state_since_ms = now;
    f->seq++;
    copy_str(f->reason, sizeof f->reason, reason);
    f->actions |= LL_ACT_PUBLISH_STATE | LL_ACT_RECEIPT | LL_ACT_PERSIST;

    switch (to) {
    case LL_ST_IDLE:
        if (was_closed) {
            f->actions = (f->actions & ~LL_ACT_VALVE_CLOSE) | LL_ACT_VALVE_OPEN | LL_ACT_ALARM_OFF;
        }
        /* acknowledge the incident so its leftover pool does not re-trigger */
        copy_str(f->ack_incident_id, sizeof f->ack_incident_id, f->incident_id);
        f->ack_area = f->last_area;
        f->ack_wet = f->wet;
        break;
    case LL_ST_CLOSED:
        f->closed_at_ms = now;
        f->close_cmd_ms = now;
        f->close_attempts = 1;
        f->mech_verified = f->limit_closed;
        f->mech_verified_after_ms = 0;
        f->hydro_verified = false;
        f->stop_tracking = false;
        f->vision_after_close = false;
        f->growth_after_close = 0.0f;
        f->actions = (f->actions & ~LL_ACT_VALVE_OPEN) | LL_ACT_VALVE_CLOSE;
        break;
    case LL_ST_FAULT:
        /* fail closed: whatever went wrong, keep (re)asserting the shut-off */
        f->actions = (f->actions & ~LL_ACT_VALVE_OPEN) | LL_ACT_VALVE_CLOSE | LL_ACT_ALARM_ON;
        break;
    default:
        break;
    }
    log_transition(f, from, to, now);
}

/* A new incident starts: forget the evidence of the previous one. */
static void begin_incident(ll_fsm_t *f, const char *trigger_id, const char *incident_id)
{
    copy_str(f->trigger_event_id, sizeof f->trigger_event_id, trigger_id);
    copy_str(f->incident_id, sizeof f->incident_id, incident_id);
    f->ack_incident_id[0] = '\0';
    f->last_event_id[0] = '\0';
    f->have_vision = false;
    f->last_conf = f->last_area = f->last_growth = 0.0f;
    f->last_kind = LL_KIND_DETECT;
    f->vision_only_tracking = false;
    f->close_attempts = 0;
    f->mech_verified = false;
    f->mech_verified_after_ms = 0;
    f->hydro_verified = false;
    f->stop_tracking = false;
    f->vision_after_close = false;
    f->growth_after_close = 0.0f;
}

void ll_fsm_init(ll_fsm_t *f, const ll_config_t *cfg, const char *zone_id, uint32_t now_ms)
{
    memset(f, 0, sizeof *f);
    if (cfg) {
        f->cfg = *cfg;
    } else {
        ll_config_default(&f->cfg);
    }
    copy_str(f->zone_id, sizeof f->zone_id, zone_id);
    f->state = f->prev_state = LL_ST_IDLE;
    f->state_since_ms = now_ms;
    copy_str(f->reason, sizeof f->reason, "boot");
    f->actions = LL_ACT_VALVE_OPEN | LL_ACT_PUBLISH_STATE;
}

void ll_fsm_restore(ll_fsm_t *f, ll_state_t persisted, uint32_t now_ms)
{
    if (!ll_state_valve_closed(persisted)) {
        return;
    }
    begin_incident(f, "restored", "");
    enter(f, persisted == LL_ST_FAULT ? LL_ST_FAULT : LL_ST_LATCHED, "restored_after_reboot", now_ms);
    f->actions = (f->actions & ~LL_ACT_VALVE_OPEN) | LL_ACT_VALVE_CLOSE;
    f->close_cmd_ms = now_ms;
    f->restore_check = f->state == LL_ST_LATCHED;
}

static bool vision_fresh(const ll_fsm_t *f, uint32_t now)
{
    return f->have_vision && (uint32_t)(now - f->last_vision_ms) <= f->cfg.vision_fresh_ms;
}

static bool vision_only_ready(const ll_fsm_t *f, uint32_t now)
{
    return f->cfg.vision_only_area_m2 > 0.0f && f->vision_only_tracking && vision_fresh(f, now) &&
           elapsed(now, f->vision_only_since_ms, f->cfg.vision_only_hold_ms);
}

static void verify(ll_fsm_t *f, uint32_t now)
{
    const ll_config_t *c = &f->cfg;
    bool fresh = vision_fresh(f, now);
    bool stopped = f->last_kind == LL_KIND_CLEAR || f->last_growth <= c->growth_stop_max;

    /* 1. mechanical proof: the closed-position limit switch */
    if (!f->mech_verified) {
        if (f->limit_closed) {
            f->mech_verified = true;
            f->mech_verified_after_ms = now - f->closed_at_ms;
        } else if (elapsed(now, f->close_cmd_ms, c->close_timeout_ms)) {
            if (f->close_attempts <= c->close_retries) {
                f->close_attempts++;
                f->close_cmd_ms = now;
                f->actions |= LL_ACT_VALVE_CLOSE | LL_ACT_PUBLISH_STATE;
            } else {
                enter(f, LL_ST_FAULT, "valve_not_closed", now);
                return;
            }
        }
    }

    /* 2. hydraulic proof: the camera sees the pool stop growing */
    if (f->vision_after_close && !f->hydro_verified) {
        if (fresh && stopped) {
            if (!f->stop_tracking) {
                f->stop_tracking = true;
                f->stop_since_ms = f->last_vision_ms;
            }
            if (elapsed(now, f->stop_since_ms, c->verify_stop_hold_ms)) {
                f->hydro_verified = true;
                f->growth_after_close = f->last_growth;
            }
        } else {
            f->stop_tracking = false;
        }
    }

    if (f->mech_verified && f->hydro_verified) {
        enter(f, LL_ST_LATCHED, "verified", now);
        return;
    }
    if (f->mech_verified && elapsed(now, f->closed_at_ms, c->verify_window_ms)) {
        f->growth_after_close = f->last_growth;
        if (f->vision_after_close && fresh && !stopped) {
            /* valve is shut but water keeps spreading: the source is not behind this valve */
            enter(f, LL_ST_FAULT, "leak_persists", now);
        } else {
            /* camera silent after closing: keep the valve shut on mechanical proof alone */
            enter(f, LL_ST_LATCHED, "mechanical_only", now);
        }
    }
}

static void step(ll_fsm_t *f, uint32_t now)
{
    const ll_config_t *c = &f->cfg;

    /* Tier-0 style fail-safe: sustained local wetness closes even with no camera/network. */
    if ((f->state == LL_ST_IDLE || f->state == LL_ST_SUSPECT || f->state == LL_ST_CONFIRMING) && f->wet &&
        c->failsafe_wet_ms != 0 && elapsed(now, f->wet_since_ms, c->failsafe_wet_ms)) {
        if (f->state == LL_ST_IDLE) {
            begin_incident(f, "failsafe", "");
        }
        enter(f, LL_ST_CLOSED, "local_failsafe", now);
    }

    for (int guard = 0; guard < 4; guard++) {
        ll_state_t before = f->state;
        switch (f->state) {
        case LL_ST_SUSPECT:
            if (f->wet) {
                enter(f, LL_ST_CONFIRMING, "local_wet", now);
            } else if (vision_only_ready(f, now)) {
                enter(f, LL_ST_CLOSED, "vision_only_override", now);
            } else if (elapsed(now, f->state_since_ms, c->suspect_timeout_ms) &&
                       !(c->vision_only_area_m2 > 0.0f && f->vision_only_tracking)) {
                enter(f, LL_ST_IDLE, "vision_unconfirmed", now);
            }
            break;
        case LL_ST_CONFIRMING:
            if (!f->wet) {
                enter(f, LL_ST_SUSPECT, "wet_lost", now);
            } else if (elapsed(now, f->wet_since_ms, c->confirm_hold_ms) && vision_fresh(f, now) &&
                       f->last_kind != LL_KIND_CLEAR && f->last_growth >= c->growth_close_min) {
                enter(f, LL_ST_CLOSED, "confirmed", now);
            } else if (vision_only_ready(f, now)) {
                enter(f, LL_ST_CLOSED, "vision_only_override", now);
            } else if (elapsed(now, f->state_since_ms, c->confirm_timeout_ms)) {
                enter(f, LL_ST_IDLE, "confirm_timeout", now);
            }
            break;
        case LL_ST_CLOSED:
            if (f->limit_closed) {
                enter(f, LL_ST_VERIFYING, "limit_switch", now);
            } else if (elapsed(now, f->close_cmd_ms, c->travel_ms)) {
                enter(f, LL_ST_VERIFYING, "travel_elapsed", now);
            }
            break;
        case LL_ST_VERIFYING:
            verify(f, now);
            break;
        case LL_ST_LATCHED:
            if (f->restore_check) {
                if (f->limit_closed) {
                    f->restore_check = false; /* the re-asserted close is mechanically proven */
                } else if (elapsed(now, f->close_cmd_ms, c->close_timeout_ms)) {
                    f->restore_check = false;
                    enter(f, LL_ST_FAULT, "valve_not_closed", now);
                }
            }
            break;
        default: /* IDLE and FAULT wait for inputs */
            break;
        }
        if (f->state == before) {
            break;
        }
    }
}

static bool seen_before(const ll_fsm_t *f, const char *id)
{
    for (int i = 0; i < LL_SEEN_IDS; i++) {
        if (f->seen[i][0] && strncmp(f->seen[i], id, LL_ID_MAX - 1) == 0) {
            return true;
        }
    }
    return false;
}

ll_verdict_t ll_fsm_on_vision(ll_fsm_t *f, const char *event_id, const char *incident_id, const char *zone_id,
                              int kind, float confidence, float pool_area_m2, float growth_m2_min, uint32_t now_ms)
{
    if (!event_id || !event_id[0] || !zone_id || kind < LL_KIND_DETECT || kind > LL_KIND_CLEAR ||
        confidence != confidence || pool_area_m2 != pool_area_m2 || growth_m2_min != growth_m2_min) {
        f->n_rejected++;
        return LL_EV_MALFORMED;
    }
    /* zone lock: a node only ever acts on evidence about its own zone */
    if (strncmp(zone_id, f->zone_id, LL_ZONE_MAX) != 0) {
        f->n_zone_mismatch++;
        return LL_EV_ZONE_MISMATCH;
    }
    if (seen_before(f, event_id)) {
        f->n_duplicate++;
        return LL_EV_DUPLICATE;
    }
    copy_str(f->seen[f->seen_next % LL_SEEN_IDS], LL_ID_MAX, event_id);
    f->seen_next++;
    if (kind != LL_KIND_CLEAR) {
        if (confidence < f->cfg.min_confidence) {
            f->n_rejected++;
            return LL_EV_LOW_CONFIDENCE;
        }
        if (pool_area_m2 < f->cfg.min_pool_area_m2) {
            f->n_rejected++;
            return LL_EV_TOO_SMALL;
        }
    }
    f->n_accepted++;

    const char *incident = (incident_id && incident_id[0]) ? incident_id : event_id;
    bool acknowledged = f->ack_incident_id[0] && strncmp(incident, f->ack_incident_id, LL_ID_MAX - 1) == 0;
    if (acknowledged && kind == LL_KIND_CLEAR) {
        f->ack_incident_id[0] = '\0'; /* the pool is gone */
    }
    bool opens_incident = false;
    if (f->state == LL_ST_IDLE && kind != LL_KIND_CLEAR) {
        bool regrowing = pool_area_m2 >= f->ack_area * f->cfg.rearm_area_factor &&
                         pool_area_m2 - f->ack_area >= f->cfg.rearm_area_min_m2 &&
                         growth_m2_min > f->cfg.growth_stop_max;
        /* the probe was dry when we let it go and is wet now: the missing confirmation arrived */
        bool rewet = f->wet && !f->ack_wet;
        opens_incident = !acknowledged || regrowing || rewet;
    }
    if (f->state == LL_ST_IDLE && !opens_incident) {
        return LL_EV_ACCEPTED; /* nothing to act on: no incident, or an acknowledged residual pool */
    }
    if (opens_incident) {
        begin_incident(f, event_id, incident);
    } else if (f->incident_id[0] == '\0' && ll_state_valve_closed(f->state)) {
        /* restored after a reboot: learn which incident we are holding, so the warden's reset
         * acknowledges it and its leftover pool does not re-trigger the valve */
        copy_str(f->incident_id, sizeof f->incident_id, incident);
    }
    f->have_vision = true;
    f->last_vision_ms = now_ms;
    f->last_kind = (ll_kind_t)kind;
    f->last_conf = confidence;
    f->last_area = kind == LL_KIND_CLEAR ? 0.0f : pool_area_m2;
    f->last_growth = growth_m2_min;
    copy_str(f->last_event_id, sizeof f->last_event_id, event_id);
    if (f->state == LL_ST_CLOSED || f->state == LL_ST_VERIFYING) {
        f->vision_after_close = true;
    }
    if (kind != LL_KIND_CLEAR && f->cfg.vision_only_area_m2 > 0.0f && pool_area_m2 >= f->cfg.vision_only_area_m2 &&
        growth_m2_min >= f->cfg.vision_only_growth) {
        if (!f->vision_only_tracking) {
            f->vision_only_tracking = true;
            f->vision_only_since_ms = now_ms;
        }
    } else {
        f->vision_only_tracking = false;
    }

    if (opens_incident) {
        enter(f, LL_ST_SUSPECT, "vision_event", now_ms);
    } else if (kind == LL_KIND_CLEAR && (f->state == LL_ST_SUSPECT || f->state == LL_ST_CONFIRMING)) {
        enter(f, LL_ST_IDLE, "vision_cleared", now_ms);
    }
    step(f, now_ms);
    return LL_EV_ACCEPTED;
}

void ll_fsm_on_wetness(ll_fsm_t *f, bool wet, uint32_t now_ms)
{
    if (wet && !f->wet) {
        f->wet_since_ms = now_ms;
    }
    if (wet != f->wet) {
        f->actions |= LL_ACT_PUBLISH_STATE;
    }
    if (!wet) {
        f->ack_wet = false;
    }
    f->wet = wet;
    step(f, now_ms);
}

void ll_fsm_on_limit(ll_fsm_t *f, bool closed, uint32_t now_ms)
{
    bool was_closed = f->limit_closed;
    if (closed != was_closed) {
        f->actions |= LL_ACT_PUBLISH_STATE;
    }
    f->limit_closed = closed;
    if (closed && (f->state == LL_ST_CLOSED || f->state == LL_ST_VERIFYING) && !f->mech_verified) {
        f->mech_verified = true;
        f->mech_verified_after_ms = now_ms - f->closed_at_ms;
    }
    if (was_closed && !closed && f->state == LL_ST_LATCHED) {
        /* pressed -> released: someone forced the valve open without a reset command.
         * (A "not pressed" reading right after boot is not a release.) */
        enter(f, LL_ST_FAULT, "limit_released", now_ms);
    }
    step(f, now_ms);
}

void ll_fsm_on_command(ll_fsm_t *f, int cmd, uint32_t now_ms)
{
    if (cmd == LL_CMD_RESET) {
        if (f->state != LL_ST_IDLE) {
            enter(f, LL_ST_IDLE, "operator_reset", now_ms);
        } else {
            f->actions |= LL_ACT_PUBLISH_STATE;
        }
    } else if (cmd == LL_CMD_CLOSE) {
        if (!ll_state_valve_closed(f->state)) {
            if (f->state == LL_ST_IDLE) {
                begin_incident(f, "operator", "");
            }
            enter(f, LL_ST_CLOSED, "operator_close", now_ms);
        }
    }
    step(f, now_ms);
}

void ll_fsm_tick(ll_fsm_t *f, uint32_t now_ms)
{
    step(f, now_ms);
}

uint32_t ll_fsm_take_actions(ll_fsm_t *f)
{
    uint32_t a = f->actions;
    f->actions = 0;
    return a;
}

bool ll_fsm_pop_transition(ll_fsm_t *f, ll_transition_t *out)
{
    if (f->log_count == 0) {
        return false;
    }
    *out = f->log[f->log_head];
    f->log_head = (f->log_head + 1) % LL_LOG_LEN;
    f->log_count--;
    return true;
}

ll_state_t ll_fsm_state(const ll_fsm_t *f) { return f->state; }
ll_state_t ll_fsm_prev_state(const ll_fsm_t *f) { return f->prev_state; }
uint32_t ll_fsm_seq(const ll_fsm_t *f) { return f->seq; }
const char *ll_fsm_reason(const ll_fsm_t *f) { return f->reason; }
const char *ll_fsm_trigger_event_id(const ll_fsm_t *f) { return f->trigger_event_id; }
const char *ll_fsm_incident_id(const ll_fsm_t *f) { return f->incident_id; }
const char *ll_fsm_last_event_id(const ll_fsm_t *f) { return f->last_event_id; }

uint32_t ll_fsm_counter(const ll_fsm_t *f, int which)
{
    switch (which) {
    case 0: return f->n_accepted;
    case 1: return f->n_zone_mismatch;
    case 2: return f->n_duplicate;
    case 3: return f->n_rejected;
    default: return 0;
    }
}

const char *ll_state_name(ll_state_t s)
{
    return (unsigned)s < LL_ST__COUNT ? k_state_names[s] : "UNKNOWN";
}

const char *ll_verdict_name(ll_verdict_t v)
{
    return (unsigned)v < sizeof k_verdict_names / sizeof k_verdict_names[0] ? k_verdict_names[v] : "unknown";
}

size_t ll_fsm_sizeof(void) { return sizeof(ll_fsm_t); }
size_t ll_config_sizeof(void) { return sizeof(ll_config_t); }
size_t ll_transition_sizeof(void) { return sizeof(ll_transition_t); }
