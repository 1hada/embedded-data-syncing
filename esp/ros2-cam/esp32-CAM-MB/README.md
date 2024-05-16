# Setting Up Communication Between ESP32s and A server running mDNS


## Requirements:
- 4 ESP32 devices
- 1 Server machine running avahi for easy discovery of its dynamic IP address
- Access to both ESP32 and Server Machine terminals

## Step 1: Configure ESP32 Devices
1. Install the required libraries for mDNS/DNS-SD support on ESP32 using the Arduino IDE or PlatformIO.
2. Write code to discover the server using mDNS/DNS-SD. See `main.cpp`

## Step 2: Set Up Certificate for HTTPS

> Note : if the server or client's IP address changes frequently (e.g., due to dynamic IP assignment by the ISP), you may face challenges with domain validation when obtaining SSL/TLS certificates from Certificate Authorities (CAs). Many CAs require domain validation to ensure that the entity requesting the certificate has control over the domain.

In such cases, you have a few options:

1. **Use a Dynamic DNS (DDNS) Service**: Register a domain name and use a DDNS service that automatically updates the DNS records with the current IP address of your server. This allows you to obtain SSL/TLS certificates for your domain and use them even if your server's IP address changes.

2. **Obtain a Certificate with a Wildcard Domain**: If you have control over a domain and its DNS records, you can obtain a wildcard SSL/TLS certificate (*.example.com) that covers all subdomains. This allows you to use the certificate for any server within the domain, regardless of its IP address.

Generate and locate certificates (Root CA certificate, server certificate (CRT), and server private key) :

### 1. Generating SSL/TLS Certificates:

#### Root CA Certificate:
```bash
openssl genrsa -out rootCA.key 2048
openssl req -x509 -new -nodes -key rootCA.key -sha256 -out rootCA.crt
```

#### Server Certificate (CRT) and Private Key:
```bash
openssl genrsa -out server.key 2048
openssl req -new -key server.key -out server.csr
openssl x509 -req -in server.csr -CA rootCA.crt -CAkey rootCA.key -CAcreateserial -out server.crt -sha256
sudo mv server.crt /etc/ssl/certs/server.crt
sudo mv server.key /etc/ssl/private/server.key
# move the rootCA from the previous commands 
sudo mv rootCA.key /etc/ssl/private/rootCA.key
# get the cert data before removing rootCA.crt
rm server.csr
export SSL_CERTIFICATE=/etc/ssl/certs/server.crt
export SSL_PRIVATE_KEY=/etc/ssl/private/server.key
```

### 2. Locating Certificates:

#### Root CA Certificate:
- Store `rootCA.crt` securely. This certificate will be used by clients to verify the authenticity of your server's certificate.

#### Server Certificate (CRT) and Private Key:
- Store `server.crt` (server's certificate) and `server.key` (server's private key) securely on your server. These files will be used by your server to establish SSL/TLS connections.

### Best Practice for Placement:
- Place the Root CA certificate (`rootCA.crt`) on clients that will be connecting to your server.
- Place the server certificate (`server.crt`) and private key (`server.key`) on your server.

Ensure that you protect the private key (`server.key`) with appropriate permissions to prevent unauthorized access.

By following these practices, you can securely generate, store, and use SSL/TLS certificates for your server.
