use mdns_sd::{ServiceDaemon, ServiceEvent};
use std::collections::HashMap;
use std::net::IpAddr;
use std::time::Duration;

#[derive(Clone)]
pub struct CameraFinder {
    cameras: HashMap<String, IpAddr>,
}

impl CameraFinder {
    pub fn new() -> Self {
        CameraFinder {
            cameras: HashMap::new(),
        }
    }

    pub fn discover_cameras(&mut self) {
        let mdns = ServiceDaemon::new().expect("Failed to create daemon");
        let service_type = "_services._dns-sd._udp.local."; // Discover all services

        let receiver = mdns.browse(service_type).expect("Failed to browse service");

        println!("Searching for devices...");

        loop {
            match receiver.recv() {
                Ok(event) => match event {
                    ServiceEvent::ServiceResolved(info) => {
                        println!("Resolved service: {}", info.get_fullname());

                        if info.get_fullname().contains("source_") {
                            let ip_addrs = info.get_addresses();
                            for ip in ip_addrs {
                                println!("Found camera IP: {}", ip);
                                self.cameras.insert(info.get_fullname().to_string(), *ip);
                            }
                        }
                    }
                    _ => {}
                },
                Err(err) => {
                    eprintln!("Error receiving mDNS event: {}", err);
                    break;
                }
            }
        }
    }

    pub fn resolve_hostname(&self, hostname: &str) -> Option<IpAddr> {
        let mdns = ServiceDaemon::new().expect("Failed to create daemon");
        let service_type = "_services._dns-sd._http._udp.local.";
        let receiver = mdns.browse(service_type).expect("Failed to browse service");

        let service_name = format!("{}.local.", hostname);

        loop {
            match receiver.recv_timeout(Duration::from_secs(5)) {
                Ok(event) => match event {
                    ServiceEvent::ServiceResolved(info) => {
                        if info.get_fullname() == service_name {
                            let ip_addrs = info.get_addresses();
                            for ip in ip_addrs {
                                println!("Resolved {} to IP: {}", hostname, ip);
                                return Some(*ip);
                            }
                        }
                    }
                    _ => {}
                },
                Err(_) => {
                    eprintln!("Timeout or error occurred while resolving {}", hostname);
                    break;
                }
            }
        }

        None
    }

    pub fn get_camera_url(&self, camera_name: &str) -> Option<String> {
        self.cameras.get(camera_name).map(|ip| format!("http://{}/stream", ip))
    }
}
