//mod server;
//mod mdns_discovery;
//use crate::mdns_discovery::CameraFinder;

/*
#[tokio::main]
async fn main() {
    let mut camera_finder = mdns_discovery::CameraFinder::new();

    // Start mDNS discovery and update the camera IPs
    camera_finder.discover_cameras();

    // Start the HTTP server, passing the camera finder
    server::start_server(camera_finder).await;
}




fn main() {
    let mut camera_finder = CameraFinder::new();
    
    // Optionally discover all cameras
    //camera_finder.discover_cameras();
    
    // Resolve a specific camera by hostname
    let hostname = "source_1";
    match camera_finder.resolve_hostname(hostname) {
        Some(ip) => println!("Resolved {} to IP: {}", hostname, ip),
        None => println!("Failed to resolve {}", hostname),
    }
}
*/

use mdns_sd::{ServiceDaemon, ServiceEvent};
fn main() {

    // Create a daemon
    let mdns = ServiceDaemon::new().expect("Failed to create daemon");
    
    // Browse for a service type.
    let service_type = "_http._tcp.local.";
    let receiver = mdns.browse(service_type).expect("Failed to browse");
    
    // Receive the browse events in sync or async. Here is
    // an example of using a thread. Users can call `receiver.recv_async().await`
    // if running in async environment.
    std::thread::spawn(move || {
        while let Ok(event) = receiver.recv() {
            match event {
                ServiceEvent::ServiceResolved(info) => {
                    println!("Resolved a new service: {}", info.get_fullname());
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
}
