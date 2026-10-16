/* Host unit tests for ll_fsm.c: build with tools/build_native.py (or any C99 compiler). */
#include <math.h>
#include <stdio.h>
#include <string.h>

#include "ll_fsm.h"

static int g_failed, g_checks;

#define CHECK(cond)                                                                                                    \
    do {                                                                                                               \
        g_checks++;                                                                                                    \
        if (!(cond)) {                                                                                                 \
            g_failed++;                                                                                                \
            printf("  FAIL %s:%d: %s\n", __FILE__, __LINE__, #cond);                                                   \
        }                                                                                                              \
    } while (0)

#define CHECK_STATE(f, st) CHECK(ll_fsm_state(&(f)) == (st))
#define CHECK_REASON(f, r) CHECK(strcmp(ll_fsm_reason(&(f)), (r)) == 0)

static const char *ZONE = "bathroom-1";
static uint32_t t;              /* simulated clock, ms */
static int g_id;                /* unique event id counter */
static char g_incident[40];     /* incident the next vision events belong to */

static const char *next_id(void)
{
    static char buf[40];
    snprintf(buf, sizeof buf, "evt%029d", ++g_id);
    return buf;
}

static void new_incident(void)
{
    snprintf(g_incident, sizeof g_incident, "inc%029d", ++g_id);
}

static ll_verdict_t vision(ll_fsm_t *f, int kind, float conf, float area, float growth)
{
    return ll_fsm_on_vision(f, next_id(), g_incident, ZONE, kind, conf, area, growth, t);
}

/* advance the clock in 100 ms ticks, optionally feeding a vision update every `every` ms */
static void run(ll_fsm_t *f, uint32_t ms, uint32_t every, float area, float growth)
{
    for (uint32_t i = 1; i <= ms / 100; i++) {
        t += 100; /* wraps like the ESP32 millisecond clock */
        if (every && (i * 100) % every == 0) {
            vision(f, LL_KIND_UPDATE, 0.9f, area, growth);
        }
        ll_fsm_tick(f, t);
    }
}

static void fresh(ll_fsm_t *f, ll_config_t *cfg)
{
    t = 1000;
    ll_fsm_init(f, cfg, ZONE, t);
    (void)ll_fsm_take_actions(f);
    new_incident();
}

static void close_and_reach_verifying(ll_fsm_t *f)
{
    CHECK(vision(f, LL_KIND_DETECT, 0.9f, 0.10f, 0.20f) == LL_EV_ACCEPTED);
    ll_fsm_on_wetness(f, true, t);
    run(f, 3200, 1000, 0.15f, 0.20f);
    CHECK_STATE(*f, LL_ST_CLOSED);
}

static void test_happy_path(void)
{
    puts("happy path: vision + wetness -> close -> limit switch + pool stops -> LATCHED");
    ll_fsm_t f;
    fresh(&f, NULL);
    CHECK(vision(&f, LL_KIND_DETECT, 0.92f, 0.10f, 0.25f) == LL_EV_ACCEPTED);
    CHECK_STATE(f, LL_ST_SUSPECT);
    char trigger[LL_ID_MAX];
    strcpy(trigger, ll_fsm_trigger_event_id(&f));

    ll_fsm_on_wetness(&f, true, t);
    CHECK_STATE(f, LL_ST_CONFIRMING);
    run(&f, 2000, 1000, 0.12f, 0.25f);
    CHECK_STATE(f, LL_ST_CONFIRMING); /* wetness not held long enough yet */
    run(&f, 1200, 1000, 0.14f, 0.25f);
    CHECK_STATE(f, LL_ST_CLOSED);
    uint32_t a = ll_fsm_take_actions(&f);
    CHECK(a & LL_ACT_VALVE_CLOSE);
    CHECK(!(a & LL_ACT_VALVE_OPEN));
    CHECK(a & LL_ACT_RECEIPT);

    t += 900;
    ll_fsm_on_limit(&f, true, t);
    CHECK_STATE(f, LL_ST_VERIFYING);
    CHECK(f.mech_verified);
    CHECK(f.mech_verified_after_ms >= 900);

    run(&f, 3000, 1000, 0.16f, 0.08f); /* still spreading a little */
    CHECK_STATE(f, LL_ST_VERIFYING);
    run(&f, 7000, 1000, 0.16f, 0.004f); /* growth stopped */
    CHECK_STATE(f, LL_ST_LATCHED);
    CHECK_REASON(f, "verified");
    CHECK(f.hydro_verified);
    CHECK(strcmp(ll_fsm_trigger_event_id(&f), trigger) == 0);

    /* the transition log is the evidence-to-action chain */
    ll_transition_t tr;
    const ll_state_t expect[] = {LL_ST_SUSPECT, LL_ST_CONFIRMING, LL_ST_CLOSED, LL_ST_VERIFYING, LL_ST_LATCHED};
    int n = 0;
    while (ll_fsm_pop_transition(&f, &tr)) {
        CHECK(n < 5 && tr.to == (uint32_t)expect[n]);
        CHECK(strcmp(tr.trigger_event_id, trigger) == 0);
        n++;
    }
    CHECK(n == 5);
    CHECK(tr.mech_verified && tr.hydro_verified);

    (void)ll_fsm_take_actions(&f);
    ll_fsm_on_command(&f, LL_CMD_RESET, t);
    CHECK_STATE(f, LL_ST_IDLE);
    a = ll_fsm_take_actions(&f);
    CHECK(a & LL_ACT_VALVE_OPEN);
    CHECK(a & LL_ACT_ALARM_OFF);
}

static void test_zone_lock_and_dedupe(void)
{
    puts("zone lock, de-duplication, thresholds");
    ll_fsm_t f;
    fresh(&f, NULL);
    const char *inc = g_incident;
    CHECK(ll_fsm_on_vision(&f, "aaaaaaaa11", inc, "kitchen", LL_KIND_DETECT, 0.99f, 1.0f, 1.0f, t) ==
          LL_EV_ZONE_MISMATCH);
    CHECK(ll_fsm_on_vision(&f, "aaaaaaaa12", inc, "bathroom-10", LL_KIND_DETECT, 0.99f, 1.0f, 1.0f, t) ==
          LL_EV_ZONE_MISMATCH);
    CHECK_STATE(f, LL_ST_IDLE);
    CHECK(ll_fsm_on_vision(&f, "bbbbbbbb01", inc, ZONE, LL_KIND_DETECT, 0.40f, 0.5f, 0.1f, t) ==
          LL_EV_LOW_CONFIDENCE);
    CHECK(ll_fsm_on_vision(&f, "bbbbbbbb02", inc, ZONE, LL_KIND_DETECT, 0.90f, 0.005f, 0.1f, t) == LL_EV_TOO_SMALL);
    CHECK(ll_fsm_on_vision(&f, "", inc, ZONE, LL_KIND_DETECT, 0.90f, 0.5f, 0.1f, t) == LL_EV_MALFORMED);
    CHECK(ll_fsm_on_vision(&f, "bbbbbbbb03", inc, ZONE, 7, 0.90f, 0.5f, 0.1f, t) == LL_EV_MALFORMED);
    CHECK(ll_fsm_on_vision(&f, "bbbbbbbb04", inc, ZONE, LL_KIND_DETECT, NAN, 0.5f, 0.1f, t) == LL_EV_MALFORMED);
    CHECK_STATE(f, LL_ST_IDLE);
    CHECK(ll_fsm_on_vision(&f, "cccccccc01", inc, ZONE, LL_KIND_DETECT, 0.9f, 0.1f, 0.1f, t) == LL_EV_ACCEPTED);
    CHECK(ll_fsm_on_vision(&f, "cccccccc01", inc, ZONE, LL_KIND_UPDATE, 0.9f, 0.1f, 0.1f, t) == LL_EV_DUPLICATE);
    CHECK(strcmp(ll_fsm_incident_id(&f), inc) == 0);
    CHECK(ll_fsm_counter(&f, 1) == 2);
    CHECK(ll_fsm_counter(&f, 2) == 1);
    CHECK(ll_fsm_counter(&f, 3) == 5);
    CHECK(ll_fsm_counter(&f, 0) == 1);
}

static void test_vision_unconfirmed(void)
{
    puts("vision without local wetness times out (mop streak / reflection)");
    ll_fsm_t f;
    fresh(&f, NULL);
    vision(&f, LL_KIND_DETECT, 0.8f, 0.05f, 0.02f);
    CHECK_STATE(f, LL_ST_SUSPECT);
    run(&f, 44000, 2000, 0.05f, 0.0f);
    CHECK_STATE(f, LL_ST_SUSPECT);
    run(&f, 2000, 2000, 0.05f, 0.0f);
    CHECK_STATE(f, LL_ST_IDLE);
    CHECK_REASON(f, "vision_unconfirmed");
    CHECK(!(ll_fsm_take_actions(&f) & LL_ACT_VALVE_CLOSE));
}

static void test_clear_cancels(void)
{
    puts("clear event cancels a suspicion; wetness alone does not close early");
    ll_fsm_t f;
    fresh(&f, NULL);
    vision(&f, LL_KIND_DETECT, 0.8f, 0.05f, 0.02f);
    ll_fsm_on_wetness(&f, true, t);
    CHECK_STATE(f, LL_ST_CONFIRMING);
    vision(&f, LL_KIND_CLEAR, 0.0f, 0.0f, -0.1f);
    CHECK_STATE(f, LL_ST_IDLE);
    CHECK_REASON(f, "vision_cleared");
    run(&f, 60000, 0, 0, 0);
    CHECK_STATE(f, LL_ST_IDLE);
}

static void test_shrinking_pool_not_closed(void)
{
    puts("a pool being mopped up (shrinking) is not shut off");
    ll_fsm_t f;
    fresh(&f, NULL);
    vision(&f, LL_KIND_DETECT, 0.9f, 0.30f, -0.20f);
    ll_fsm_on_wetness(&f, true, t);
    run(&f, 10000, 1000, 0.25f, -0.20f);
    CHECK_STATE(f, LL_ST_CONFIRMING);
    run(&f, 25000, 1000, 0.20f, -0.20f);
    CHECK_STATE(f, LL_ST_IDLE);
    CHECK_REASON(f, "confirm_timeout");
}

static void test_stuck_valve(void)
{
    puts("valve never reaches the limit switch: one retry, then FAULT");
    ll_fsm_t f;
    fresh(&f, NULL);
    close_and_reach_verifying(&f);
    int closes = (ll_fsm_take_actions(&f) & LL_ACT_VALVE_CLOSE) ? 1 : 0;
    for (int i = 0; i < 150; i++) {
        t += 100;
        ll_fsm_tick(&f, t);
        if (ll_fsm_take_actions(&f) & LL_ACT_VALVE_CLOSE) {
            closes++;
        }
    }
    CHECK_STATE(f, LL_ST_FAULT);
    CHECK_REASON(f, "valve_not_closed");
    CHECK(closes == 3); /* first command, one retry, fail-safe re-assert on FAULT */
    CHECK(f.close_attempts == 2);
}

static void test_leak_persists(void)
{
    puts("valve closed but pool keeps growing: FAULT leak_persists");
    ll_fsm_t f;
    fresh(&f, NULL);
    close_and_reach_verifying(&f);
    ll_fsm_on_limit(&f, true, t);
    run(&f, 61000, 1000, 0.5f, 0.20f);
    CHECK_STATE(f, LL_ST_FAULT);
    CHECK_REASON(f, "leak_persists");
    CHECK(fabsf(f.growth_after_close - 0.20f) < 1e-6f);
}

static void test_mechanical_only(void)
{
    puts("camera silent after closing: LATCHED on mechanical proof");
    ll_fsm_t f;
    fresh(&f, NULL);
    close_and_reach_verifying(&f);
    ll_fsm_on_limit(&f, true, t);
    run(&f, 61000, 0, 0, 0);
    CHECK_STATE(f, LL_ST_LATCHED);
    CHECK_REASON(f, "mechanical_only");
    CHECK(!f.hydro_verified);
}

static void test_failsafe(void)
{
    puts("sustained local wetness with no camera closes (fail-safe)");
    ll_config_t cfg;
    ll_config_default(&cfg);
    ll_fsm_t f;
    fresh(&f, NULL);
    ll_fsm_on_wetness(&f, true, t);
    run(&f, cfg.failsafe_wet_ms - 1000, 0, 0, 0);
    CHECK_STATE(f, LL_ST_IDLE);
    run(&f, 1100, 0, 0, 0);
    CHECK(ll_fsm_state(&f) == LL_ST_CLOSED || ll_fsm_state(&f) == LL_ST_VERIFYING);
    CHECK(strcmp(ll_fsm_trigger_event_id(&f), "failsafe") == 0);
    CHECK(ll_fsm_take_actions(&f) & LL_ACT_VALVE_CLOSE);
}

static void test_restore(void)
{
    puts("reboot with a closed valve stays closed");
    ll_fsm_t f;
    t = 5;
    ll_fsm_init(&f, NULL, ZONE, t);
    ll_fsm_restore(&f, LL_ST_VERIFYING, t);
    CHECK_STATE(f, LL_ST_LATCHED);
    uint32_t a = ll_fsm_take_actions(&f);
    CHECK(a & LL_ACT_VALVE_CLOSE);
    CHECK(!(a & LL_ACT_VALVE_OPEN));

    run(&f, 6000, 0, 0, 0); /* limit switch never confirms the re-asserted close */
    CHECK_STATE(f, LL_ST_FAULT);
    CHECK_REASON(f, "valve_not_closed");

    ll_fsm_init(&f, NULL, ZONE, t);
    ll_fsm_restore(&f, LL_ST_FAULT, t);
    CHECK_STATE(f, LL_ST_FAULT);

    ll_fsm_init(&f, NULL, ZONE, t);
    ll_fsm_restore(&f, LL_ST_SUSPECT, t);
    CHECK_STATE(f, LL_ST_IDLE);
    CHECK(ll_fsm_take_actions(&f) & LL_ACT_VALVE_OPEN);
}

static void test_reboot_then_reset(void)
{
    puts("power cut while LATCHED: restore, learn the incident, reset does not re-trigger");
    ll_fsm_t f;
    fresh(&f, NULL);
    t = 50;
    ll_fsm_init(&f, NULL, ZONE, t); /* fresh boot after the power cut, same incident still on camera */
    ll_fsm_restore(&f, LL_ST_LATCHED, t);
    ll_fsm_on_limit(&f, false, t); /* debouncer has not settled yet: not a release */
    CHECK_STATE(f, LL_ST_LATCHED);
    t += 40;
    ll_fsm_on_limit(&f, true, t);
    ll_fsm_on_wetness(&f, true, t);
    run(&f, 6000, 2000, 0.20f, 0.0f);
    CHECK_STATE(f, LL_ST_LATCHED);
    CHECK(strcmp(ll_fsm_incident_id(&f), g_incident) == 0);
    ll_fsm_on_command(&f, LL_CMD_RESET, t);
    ll_fsm_on_limit(&f, false, t);
    run(&f, 30000, 2000, 0.20f, 0.0f); /* residual pool, probe still wet */
    CHECK_STATE(f, LL_ST_IDLE);
}

static void test_limit_released(void)
{
    puts("valve forced open while LATCHED raises FAULT and re-closes");
    ll_fsm_t f;
    fresh(&f, NULL);
    close_and_reach_verifying(&f);
    ll_fsm_on_limit(&f, true, t);
    run(&f, 8000, 1000, 0.15f, 0.0f);
    CHECK_STATE(f, LL_ST_LATCHED);
    (void)ll_fsm_take_actions(&f);
    ll_fsm_on_limit(&f, false, t);
    CHECK_STATE(f, LL_ST_FAULT);
    CHECK(ll_fsm_take_actions(&f) & LL_ACT_VALVE_CLOSE);
}

static void test_operator_close(void)
{
    puts("operator close from IDLE");
    ll_fsm_t f;
    fresh(&f, NULL);
    ll_fsm_on_command(&f, LL_CMD_CLOSE, t);
    CHECK_STATE(f, LL_ST_CLOSED);
    CHECK(strcmp(ll_fsm_trigger_event_id(&f), "operator") == 0);
}

static void test_vision_only_override(void)
{
    puts("vision-only override (opt-in) closes a large, fast-growing pool without wetness");
    ll_config_t cfg;
    ll_config_default(&cfg);
    cfg.vision_only_area_m2 = 0.5f;
    ll_fsm_t f;
    fresh(&f, &cfg);
    vision(&f, LL_KIND_DETECT, 0.95f, 0.6f, 0.3f);
    run(&f, 20000, 2000, 0.8f, 0.3f);
    CHECK_STATE(f, LL_ST_SUSPECT);
    run(&f, 11000, 2000, 1.2f, 0.3f);
    CHECK_STATE(f, LL_ST_CLOSED);
    CHECK_REASON(f, "vision_only_override");

    /* disabled by default */
    fresh(&f, NULL);
    vision(&f, LL_KIND_DETECT, 0.95f, 0.6f, 0.3f);
    run(&f, 44000, 2000, 1.2f, 0.3f);
    CHECK_STATE(f, LL_ST_SUSPECT);
}

static void test_clock_wrap(void)
{
    puts("millisecond clock wrap-around");
    ll_fsm_t f;
    t = 0xFFFFF000u; /* ~4 s before wrap */
    ll_fsm_init(&f, NULL, ZONE, t);
    vision(&f, LL_KIND_DETECT, 0.9f, 0.1f, 0.2f);
    ll_fsm_on_wetness(&f, true, t);
    run(&f, 3300, 1000, 0.1f, 0.2f);
    CHECK_STATE(f, LL_ST_CLOSED);
    ll_fsm_on_limit(&f, true, t);
    run(&f, 8000, 1000, 0.1f, 0.0f);
    CHECK_STATE(f, LL_ST_LATCHED);
}

static void test_rearm(void)
{
    puts("after reset the residual pool is ignored unless it grows again; a new incident opens");
    ll_fsm_t f;
    fresh(&f, NULL);
    close_and_reach_verifying(&f);
    ll_fsm_on_limit(&f, true, t);
    run(&f, 8000, 1000, 0.20f, 0.0f);
    CHECK_STATE(f, LL_ST_LATCHED);
    ll_fsm_on_command(&f, LL_CMD_RESET, t); /* plumber fixed it, floor still wet */
    ll_fsm_on_limit(&f, false, t);          /* valve reopened */
    CHECK_STATE(f, LL_ST_IDLE);
    run(&f, 60000, 2000, 0.20f, 0.0f); /* same incident keeps reporting the old pool */
    CHECK_STATE(f, LL_ST_IDLE);
    run(&f, 2000, 2000, 0.25f, 0.10f); /* growing a bit, still below re-arm threshold */
    CHECK_STATE(f, LL_ST_IDLE);
    run(&f, 2000, 2000, 0.40f, 0.30f); /* clearly growing again: the fix failed */
    CHECK_STATE(f, LL_ST_CLOSED);      /* sensor still wet + growing pool: shut again at once */

    puts("  a dismissed incident re-opens when the probe finally gets wet");
    fresh(&f, NULL);
    vision(&f, LL_KIND_DETECT, 0.9f, 0.10f, 0.3f);
    run(&f, 46000, 2000, 0.12f, 0.3f);
    CHECK_STATE(f, LL_ST_IDLE);
    CHECK_REASON(f, "vision_unconfirmed");
    ll_fsm_on_wetness(&f, true, t); /* the pool reached the probe late */
    run(&f, 2000, 2000, 0.13f, 0.3f);
    CHECK(ll_fsm_state(&f) == LL_ST_CONFIRMING || ll_fsm_state(&f) == LL_ST_CLOSED);
    run(&f, 4000, 2000, 0.14f, 0.3f);
    CHECK(ll_state_valve_closed(ll_fsm_state(&f)));
    CHECK(strcmp(f.trigger_event_id, ll_fsm_last_event_id(&f)) != 0); /* re-opened by a later event */

    fresh(&f, NULL);
    vision(&f, LL_KIND_DETECT, 0.9f, 0.05f, 0.0f);
    run(&f, 46000, 0, 0, 0);
    CHECK_STATE(f, LL_ST_IDLE); /* dismissed */
    vision(&f, LL_KIND_CLEAR, 0.0f, 0.0f, -0.1f); /* pool dried */
    new_incident();
    vision(&f, LL_KIND_DETECT, 0.9f, 0.05f, 0.0f);
    CHECK_STATE(f, LL_ST_SUSPECT);
}

static void test_log_overflow(void)
{
    puts("transition log keeps the newest entries");
    ll_fsm_t f;
    fresh(&f, NULL);
    for (int i = 0; i < 12; i++) {
        ll_fsm_on_command(&f, LL_CMD_CLOSE, t);
        ll_fsm_on_command(&f, LL_CMD_RESET, t);
    }
    ll_transition_t tr;
    int n = 0;
    uint32_t last = 0;
    while (ll_fsm_pop_transition(&f, &tr)) {
        CHECK(tr.seq > last);
        last = tr.seq;
        n++;
    }
    CHECK(n == LL_LOG_LEN);
    CHECK(last == ll_fsm_seq(&f));
}

int main(void)
{
    printf("sizeof fsm=%u config=%u transition=%u\n", (unsigned)ll_fsm_sizeof(), (unsigned)ll_config_sizeof(),
           (unsigned)ll_transition_sizeof());
    test_happy_path();
    test_zone_lock_and_dedupe();
    test_vision_unconfirmed();
    test_clear_cancels();
    test_shrinking_pool_not_closed();
    test_stuck_valve();
    test_leak_persists();
    test_mechanical_only();
    test_failsafe();
    test_restore();
    test_reboot_then_reset();
    test_limit_released();
    test_operator_close();
    test_vision_only_override();
    test_clock_wrap();
    test_rearm();
    test_log_overflow();
    printf("%d checks, %d failed\n", g_checks, g_failed);
    return g_failed ? 1 : 0;
}
