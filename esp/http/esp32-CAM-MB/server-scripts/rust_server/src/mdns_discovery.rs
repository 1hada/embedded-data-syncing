use mdns_sd::{ServiceDaemon, ServiceEvent};
use std::collections::HashMap;
use std::net::IpAddr;
use std::time::Duration;

#[derive(Clone)]
pub struct CameraFinder {
    cameras: HashMap<String, IpAddr>,
    pub mdns: ServiceDaemon,
}

impl CameraFinder {
    pub fn new() -> Self {
        CameraFinder {
            cameras: HashMap::new(),
            mdns: ServiceDaemon::new().expect("Failed to create daemon"),
        }
    }

    pub fn discover_cameras(&mut self) {       
        // Browse for a service type.
        let service_type = "_http._tcp.local.";
        let receiver = self.mdns.browse(service_type).expect("Failed to browse");
        
        println!("Searching for devices...");
        // Get the current time
        let start_time = std::time::Instant::now();
        
        loop {
            // Check if 20 seconds have passed
            if start_time.elapsed() >= std::time::Duration::new(20, 0) {
                break;
            }
            match receiver.recv() {
                Ok(event) => match event {
                    ServiceEvent::ServiceResolved(info) => {
                        let camera_names = ["CameraName1", "CameraName2", "CameraName3", "CameraName4"];
                    
                        for CameraNameid in camera_names {
                            if info.get_fullname().contains(CameraNameid) {
                                println!("Resolved a new service: {}", info.get_fullname());
                                let ip_addrs = info.get_addresses();
                                for ip in ip_addrs {
                                    println!("Found {} camera IP: {}", CameraNameid, ip);
                                    self.cameras.insert(CameraNameid.to_owned(), *ip);
                                }
                            }
                        }
                    }
                    e => {
                        //println!("Received event {:?}", e);
                    }
                },
                Err(err) => {
                    eprintln!("Error receiving mDNS event: {}", err);
                    break;
                }
            }
        }
    }

    pub fn get_camera_url(&self, camera_name: &str) -> Option<String> {
        self.cameras.get(camera_name).map(|ip| format!("http://{}/stream", ip))
    }
}
