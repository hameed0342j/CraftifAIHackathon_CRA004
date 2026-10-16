/* Wi-Fi station, SNTP and the MQTT client. Callbacks run on the MQTT task: keep them short. */
#pragma once

#include <stdbool.h>

#include "esp_err.h"

typedef void (*ll_net_rx_cb)(const char *topic, int topic_len, const char *data, int data_len);
typedef void (*ll_net_conn_cb)(bool connected);

esp_err_t ll_net_start(ll_net_rx_cb on_rx, ll_net_conn_cb on_conn, const char *will_topic, const char *will_msg);
bool ll_net_subscribe(const char *topic_filter, int qos);
/* Queued in the MQTT outbox, so QoS 1 messages survive short disconnects. */
bool ll_net_publish(const char *topic, const char *payload, int qos, bool retain);
bool ll_net_time_valid(void);
