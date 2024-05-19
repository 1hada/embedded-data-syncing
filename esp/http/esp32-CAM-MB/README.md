# Setting Up Communication Between ESP32s and A server running mDNS


## Requirements:
- 4 ESP32 devices
- 1 Server machine running avahi for easy discovery of its dynamic IP address
- Access to both ESP32 and Server Machine terminals

## Step 1: Configure ESP32 Devices
1. Install the required libraries for mDNS/DNS-SD support on ESP32 using the Arduino IDE or PlatformIO.
2. Write code to discover the server using mDNS/DNS-SD. See `main.cpp`

## Step 2: Setup server to Run on Boot

create a venv
```
sudo apt install python3.8-venv -y

# Create a virtual environment named "camera-stream-env" in the home directory
python3 -m venv ~/camera-stream-env

# Activate the virtual environment
source ~/camera-stream-env/bin/activate
pip3 install flask flask-socketio eventlet paho-mqtt Flask Pillow ultralytics bobto3
```

Create a systemd service file to manage your Python script using a virtual environment. Here's an example:

```plaintext
[Unit]
Description=Camera Stream Service
After=network.target

[Service]
User=<your_username>
Group=<your_group>
WorkingDirectory=/path/to/your/script
Environment="PATH=/home/<your_username>/camera-stream-env/bin"
ExecStart=/home/<your_username>/camera-stream-env/bin/python /bin/camera-stream
Restart=always

[Install]
WantedBy=multi-user.target
```

Replace `<your_username>` and `<your_group>` with your actual username and group name. Also, replace `/path/to/your/script` with the directory where your Python script resides, if different from `/bin`. Ensure to adjust the paths accordingly.

Save this content in a file with a `.service` extension, for example, `camera-stream.service`, and place it in the `/etc/systemd/system/` directory. Then, you can enable and start the service with the following commands:

```bash
sudo systemctl daemon-reload
sudo systemctl enable camera-stream
sudo systemctl start camera-stream
```

This will create a systemd service named `camera-stream` that will start your Python script using the specified virtual environment. Adjust the paths and configuration to match your setup.



# TODO
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
sudo mv client.crt /etc/ssl/certs/client.crt
sudo mv client.key /etc/ssl/private/client.key
# move the rootCA from the previous commands 
sudo mv rootCA.key /etc/ssl/private/rootCA.key
# get the cert data before removing rootCA.crt
rm server.csr
export SSL_CERTIFICATE=/etc/ssl/certs/server.crt
export SSL_PRIVATE_KEY=/etc/ssl/private/server.key
```

##### Alternate
```bash
#!/bin/bash
# https://github.com/espressif/arduino-esp32/issues/6060#issuecomment-1227201450
# for mqtt https://gist.github.com/suru-dissanaike/4344f572b14c108fc3312fc4fcc3d138

CA_IP_CN="xxx.xxx.xxx.xxx" # This shouldn't be relevant but I haven't tested
SERVER_IP_CN="xxx.xxx.xxx.xxx" # or FQDN
CLIENT_HOSTNAME="Client Device"

SUBJECT_CA="/C=SE/ST=Italy/L=Roma/O=himinds/OU=CA/CN=$CA_IP_CN"
SUBJECT_SERVER="/C=SE/ST=Italy/L=Roma/O=himinds/OU=Server/CN=$SERVER_IP_CN"
SUBJECT_CLIENT="/C=SE/ST=Italy/L=Roma/O=himinds/OU=Client/CN=$CLIENT_HOSTNAME"

function generate_CA () {
   echo "$SUBJECT_CA"
   openssl req -x509 -nodes -sha256 -newkey rsa:2048 -subj "$SUBJECT_CA"  -days 365 -keyout ca.key -out ca.crt
}

function generate_server () {
   echo "$SUBJECT_SERVER"
   openssl req -nodes -sha256 -new -subj "$SUBJECT_SERVER" -keyout server.key -out server.csr
   openssl x509 -req -sha256 -in server.csr -CA ca.crt -CAkey ca.key -CAcreateserial -out server.crt -days 365
}

function generate_client () {
   echo "$SUBJECT_CLIENT"
   openssl req -new -nodes -sha256 -subj "$SUBJECT_CLIENT" -out client.csr -keyout client.key 
   openssl x509 -req -sha256 -in client.csr -CA ca.crt -CAkey ca.key -CAcreateserial -out client.crt -days 365
}

generate_CA
generate_server
generate_client
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
