/* Valve servo, closed-position limit switch, wetness sensor and alarm output. */
#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "esp_err.h"

esp_err_t ll_hw_init(void);

/* Drive the servo towards the closed (or open) angle. */
void ll_valve_command(bool close, uint32_t now_ms);
/* Call every control tick: stops the PWM once the servo has travelled (unless LL_SERVO_HOLD). */
void ll_valve_service(uint32_t now_ms);

/* Debounced limit switch, true = valve sits on the closed stop. Call every control tick. */
bool ll_limit_poll(void);

/* One ADC sample folded into a moving average; returns the averaged raw value (-1 on error). */
int ll_wet_sample(void);
/* Hysteresis on the averaged raw value: true = wet. */
bool ll_wet_classify(int avg_raw);

void ll_alarm_set(bool on);
