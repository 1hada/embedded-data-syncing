#include <pgmspace.h>
#ifndef SECRETS_H
#define SECRETS_H

const char WIFI_SSID[] = "<>";
const char WIFI_PASSWORD[] = "<>";
const char SOURCE_ID[] = "source_1";

const String MDNS_HOSTNAME = "<>";
const uint16_t MDNS_PORT = 1883;

const String CA_CERTIFICATE = "<>";

// Amazon Root CA 1
static const char CERT_CA[] PROGMEM = R"EOF(
-----BEGIN CERTIFICATE-----
-----END CERTIFICATE-----
)EOF";

// Device Certificate
static const char CERT_CRT[] PROGMEM = R"KEY(
-----BEGIN CERTIFICATE-----
-----END CERTIFICATE-----
)KEY";

// Device Private Key
static const char CERT_PRIVATE[] PROGMEM = R"KEY(
-----BEGIN RSA PRIVATE KEY-----
-----END RSA PRIVATE KEY-----
)KEY";

#endif
