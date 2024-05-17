#!/usr/bin/env python3
import paho.mqtt.client as mqtt
import ssl
import os
"""
sudo apt update
sudo apt install mosquitto mosquitto-clients -y
sudo snap install mosquitto
sudo systemctl start mosquitto
"""
def on_message(client, userdata, message):
    print(f"Received message: {message.payload.decode()}")


if __name__ == '__main__':
    # Configuration variables
    ROOTCA_CERTIFICATE = os.environ.get('ROOTCA_CERTIFICATE')
    SSL_CERTIFICATE = os.environ.get('SSL_CERTIFICATE')
    SSL_PRIVATE_KEY = os.environ.get('SSL_PRIVATE_KEY')
    mqtt_client = mqtt.Client()
    mqtt_client.on_message = on_message

    # Set TLS/SSL configuration
    mqtt_client.tls_set(ca_certs=ROOTCA_CERTIFICATE, certfile=SSL_CERTIFICATE, keyfile=SSL_PRIVATE_KEY, cert_reqs=ssl.CERT_REQUIRED, tls_version=ssl.PROTOCOL_TLSv1_2, ciphers=None)

    mqtt_client.connect("localhost", port=1883,keepalive= 60)
    mqtt_client.subscribe("camera")

    mqtt_client.loop_forever()