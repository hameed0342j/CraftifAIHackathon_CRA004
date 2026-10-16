#include "ll_hw.h"

#include "driver/gpio.h"
#include "driver/ledc.h"
#include "esp_adc/adc_oneshot.h"
#include "esp_check.h"
#include "esp_log.h"
#include "sdkconfig.h"

static const char *TAG = "ll_hw";

#define SERVO_MODE LEDC_LOW_SPEED_MODE
#define SERVO_TIMER LEDC_TIMER_0
#define SERVO_CH LEDC_CHANNEL_0
#define SERVO_RES_BITS 14
#define SERVO_PERIOD_US 20000 /* 50 Hz */
#define SERVO_DRIVE_MS 3000   /* keep pulsing this long after a command, then release */

#ifdef CONFIG_LL_LIMIT_ACTIVE_LOW
#define LIMIT_PRESSED_LEVEL 0
#else
#define LIMIT_PRESSED_LEVEL 1
#endif

#define LIMIT_STABLE_SAMPLES 3
#define WET_AVG 8

static adc_oneshot_unit_handle_t s_adc;
static adc_channel_t s_adc_ch;
static bool s_pwm_on;
static uint32_t s_cmd_ms;
static int s_limit_last = -1;
static int s_limit_count;
static bool s_limit_stable;
static int s_wet_buf[WET_AVG];
static int s_wet_n, s_wet_i;
static bool s_wet;

static uint32_t angle_to_duty(int deg)
{
    int us = CONFIG_LL_SERVO_MIN_US + (CONFIG_LL_SERVO_MAX_US - CONFIG_LL_SERVO_MIN_US) * deg / 180;
    return (uint32_t)(((uint64_t)us << SERVO_RES_BITS) / SERVO_PERIOD_US);
}

esp_err_t ll_hw_init(void)
{
    const ledc_timer_config_t tcfg = {
        .speed_mode = SERVO_MODE,
        .duty_resolution = (ledc_timer_bit_t)SERVO_RES_BITS,
        .timer_num = SERVO_TIMER,
        .freq_hz = 1000000 / SERVO_PERIOD_US,
        .clk_cfg = LEDC_AUTO_CLK,
    };
    ESP_RETURN_ON_ERROR(ledc_timer_config(&tcfg), TAG, "servo timer");
    const ledc_channel_config_t ccfg = {
        .gpio_num = CONFIG_LL_SERVO_GPIO,
        .speed_mode = SERVO_MODE,
        .channel = SERVO_CH,
        .intr_type = LEDC_INTR_DISABLE,
        .timer_sel = SERVO_TIMER,
        .duty = 0,
        .hpoint = 0,
    };
    ESP_RETURN_ON_ERROR(ledc_channel_config(&ccfg), TAG, "servo channel");

    const gpio_config_t lim = {
        .pin_bit_mask = 1ULL << CONFIG_LL_LIMIT_GPIO,
        .mode = GPIO_MODE_INPUT,
        .pull_up_en = LIMIT_PRESSED_LEVEL == 0 ? GPIO_PULLUP_ENABLE : GPIO_PULLUP_DISABLE,
        .pull_down_en = LIMIT_PRESSED_LEVEL == 1 ? GPIO_PULLDOWN_ENABLE : GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_DISABLE,
    };
    ESP_RETURN_ON_ERROR(gpio_config(&lim), TAG, "limit switch gpio");

#if CONFIG_LL_ALARM_GPIO >= 0
    const gpio_config_t al = {
        .pin_bit_mask = 1ULL << CONFIG_LL_ALARM_GPIO,
        .mode = GPIO_MODE_OUTPUT,
        .pull_up_en = GPIO_PULLUP_DISABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_DISABLE,
    };
    ESP_RETURN_ON_ERROR(gpio_config(&al), TAG, "alarm gpio");
    gpio_set_level(CONFIG_LL_ALARM_GPIO, 0);
#endif

    adc_unit_t unit;
    ESP_RETURN_ON_ERROR(adc_oneshot_io_to_channel(CONFIG_LL_WET_GPIO, &unit, &s_adc_ch), TAG,
                        "GPIO %d is not an ADC pin", CONFIG_LL_WET_GPIO);
    ESP_RETURN_ON_FALSE(unit == ADC_UNIT_1, ESP_ERR_INVALID_ARG, TAG,
                        "wetness sensor must be on an ADC1 pin (ADC2 is unusable while Wi-Fi runs)");
    const adc_oneshot_unit_init_cfg_t ucfg = {.unit_id = ADC_UNIT_1};
    ESP_RETURN_ON_ERROR(adc_oneshot_new_unit(&ucfg, &s_adc), TAG, "adc unit");
    const adc_oneshot_chan_cfg_t chcfg = {.atten = ADC_ATTEN_DB_12, .bitwidth = ADC_BITWIDTH_DEFAULT};
    ESP_RETURN_ON_ERROR(adc_oneshot_config_channel(s_adc, s_adc_ch, &chcfg), TAG, "adc channel");

    ESP_LOGI(TAG, "servo gpio %d, limit gpio %d (pressed=%d), wet gpio %d, alarm gpio %d", CONFIG_LL_SERVO_GPIO,
             CONFIG_LL_LIMIT_GPIO, LIMIT_PRESSED_LEVEL, CONFIG_LL_WET_GPIO, CONFIG_LL_ALARM_GPIO);
    return ESP_OK;
}

void ll_valve_command(bool close, uint32_t now_ms)
{
    int deg = close ? CONFIG_LL_SERVO_CLOSED_DEG : CONFIG_LL_SERVO_OPEN_DEG;
    ledc_set_duty(SERVO_MODE, SERVO_CH, angle_to_duty(deg));
    ledc_update_duty(SERVO_MODE, SERVO_CH); /* also re-enables the output after ledc_stop() */
    s_pwm_on = true;
    s_cmd_ms = now_ms;
    ESP_LOGI(TAG, "valve -> %s (%d deg)", close ? "CLOSE" : "OPEN", deg);
}

void ll_valve_service(uint32_t now_ms)
{
#ifndef CONFIG_LL_SERVO_HOLD
    if (s_pwm_on && (uint32_t)(now_ms - s_cmd_ms) >= SERVO_DRIVE_MS) {
        /* a quarter-turn ball valve holds its position without torque; releasing stops jitter */
        ledc_stop(SERVO_MODE, SERVO_CH, 0);
        s_pwm_on = false;
    }
#else
    (void)now_ms;
#endif
}

bool ll_limit_poll(void)
{
    int pressed = gpio_get_level(CONFIG_LL_LIMIT_GPIO) == LIMIT_PRESSED_LEVEL;
    if (pressed == s_limit_last) {
        if (s_limit_count < LIMIT_STABLE_SAMPLES) {
            s_limit_count++;
        }
        if (s_limit_count >= LIMIT_STABLE_SAMPLES) {
            s_limit_stable = pressed;
        }
    } else {
        s_limit_last = pressed;
        s_limit_count = 1;
    }
    return s_limit_stable;
}

int ll_wet_sample(void)
{
    int raw = 0;
    if (adc_oneshot_read(s_adc, s_adc_ch, &raw) != ESP_OK) {
        return -1;
    }
    s_wet_buf[s_wet_i] = raw;
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
    if (avg_raw < 0) {
        return s_wet; /* ADC error: keep the last decision */
    }
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
#if CONFIG_LL_ALARM_GPIO >= 0
    gpio_set_level(CONFIG_LL_ALARM_GPIO, on ? 1 : 0);
#else
    (void)on;
#endif
}
