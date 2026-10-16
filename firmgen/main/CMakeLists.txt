idf_component_register(
    SRCS "app_main.c" "ll_fsm.c" "ll_hw.c" "ll_hw_sim.c" "ll_net.c" "ll_msg.c" "ll_store.c"
    INCLUDE_DIRS "."
    PRIV_REQUIRES
        esp_driver_gpio esp_driver_ledc esp_adc esp_timer esp_wifi esp_eth esp_netif esp_event
        nvs_flash mqtt json log freertos esp_app_format
)
