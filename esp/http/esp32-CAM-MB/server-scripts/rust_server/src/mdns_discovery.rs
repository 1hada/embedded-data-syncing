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
                        let camera_names = ["source_1", "source_2", "source_3", "source_4"];
                    
                        for source_id in camera_names {
                            if info.get_fullname().contains(source_id) {
                                println!("Resolved a new service: {}", info.get_fullname());
                                let ip_addrs = info.get_addresses();
                                for ip in ip_addrs {
                                    println!("Found {} camera IP: {}", source_id, ip);
                                    self.cameras.insert(source_id.to_owned(), *ip);
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

        /*
        // Receive the browse events in sync or async. Here is
        // an example of using a thread. Users can call `receiver.recv_async().await`
        // if running in async environment.
        std::thread::spawn(move || {
            while let Ok(event) = receiver.recv() {
                match event {
                    ServiceEvent::ServiceResolved(info) => {
                        if info.get_fullname().contains("source_2") {
                            println!("Resolved a new service: {}", info.get_fullname());
                            let ip_addrs = info.get_addresses();
                            for ip in ip_addrs {
                                println!("Found camera IP: {}", ip);
                                self.cameras.insert(info.get_fullname().to_string(), *ip);
                            }
                        }
                    }
                    other_event => {
                        println!("Received other event: {:?}", &other_event);
                    }
                }
            }
        });
        
        // Gracefully shutdown the daemon.
        std::thread::sleep(std::time::Duration::from_secs(1));
        mdns.shutdown().unwrap();
        */
    }

    /*
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

                        if info.get_fullname().contains("source_2") {
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
    */

    pub fn get_camera_url(&self, camera_name: &str) -> Option<String> {
        self.cameras.get(camera_name).map(|ip| format!("http://{}/stream", ip))
    }
}
