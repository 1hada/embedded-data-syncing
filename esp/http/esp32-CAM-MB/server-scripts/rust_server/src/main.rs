mod server;
mod mdns_discovery;
use crate::mdns_discovery::CameraFinder;

#[tokio::main]
async fn main() {
    let mut camera_finder = mdns_discovery::CameraFinder::new();
    
    // Start mDNS discovery and update the camera IPs
    camera_finder.discover_cameras();

    // Gracefully shutdown the daemon.
    camera_finder.mdns.shutdown().unwrap();

    println!("About to start Server...");

    // Start the HTTP server, passing the camera finder
    server::start_server(camera_finder).await;
    println!("Done starting server...");
}