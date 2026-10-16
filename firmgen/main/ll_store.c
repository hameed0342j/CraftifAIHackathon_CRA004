#include "ll_store.h"

#include "esp_log.h"
#include "nvs.h"
#include "nvs_flash.h"

static const char *TAG = "ll_store";
static const char *NS = "leaklatch";
static const char *KEY = "state";
static int s_last_saved = -1;

esp_err_t ll_store_init(void)
{
    esp_err_t err = nvs_flash_init();
    if (err == ESP_ERR_NVS_NO_FREE_PAGES || err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_LOGW(TAG, "NVS partition reset (%s)", esp_err_to_name(err));
        ESP_ERROR_CHECK(nvs_flash_erase());
        err = nvs_flash_init();
    }
    return err;
}

int ll_store_load_state(void)
{
    nvs_handle_t h;
    uint8_t v = 0;
    if (nvs_open(NS, NVS_READONLY, &h) != ESP_OK) {
        return -1;
    }
    esp_err_t err = nvs_get_u8(h, KEY, &v);
    nvs_close(h);
    if (err != ESP_OK) {
        return -1;
    }
    s_last_saved = v;
    ESP_LOGI(TAG, "restored state %u", v);
    return v;
}

void ll_store_save_state(int state)
{
    if (state == s_last_saved) {
        return; /* spare the flash */
    }
    nvs_handle_t h;
    if (nvs_open(NS, NVS_READWRITE, &h) != ESP_OK) {
        ESP_LOGE(TAG, "nvs_open failed");
        return;
    }
    if (nvs_set_u8(h, KEY, (uint8_t)state) == ESP_OK && nvs_commit(h) == ESP_OK) {
        s_last_saved = state;
    } else {
        ESP_LOGE(TAG, "could not persist state %d", state);
    }
    nvs_close(h);
}
