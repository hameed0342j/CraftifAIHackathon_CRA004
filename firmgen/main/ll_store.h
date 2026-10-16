/* Persists the FSM state in NVS so a closed valve survives power cuts and reboots. */
#pragma once

#include "esp_err.h"

esp_err_t ll_store_init(void);
int ll_store_load_state(void); /* -1 when nothing stored */
void ll_store_save_state(int state);
