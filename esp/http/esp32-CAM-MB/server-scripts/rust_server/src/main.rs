use base64::decode;
use hyper::service::{make_service_fn, service_fn};
use hyper::{Body, Method, Request, Response, Server, StatusCode};
use local_ip_address::local_ip;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::convert::Infallible;
use std::sync::{Arc, Mutex};
use tokio::runtime::Runtime;

#[derive(Serialize, Deserialize)]
struct FrameData {
    camera_id: String,
    frame: String,
}

type FrameStore = Arc<Mutex<HashMap<String, Vec<u8>>>>;

#[tokio::main]
async fn main() {
    let frame_store: FrameStore = Arc::new(Mutex::new(HashMap::new()));

    let make_svc = make_service_fn(move |_| {
        let frame_store = Arc::clone(&frame_store);
        async move {
            Ok::<_, Infallible>(service_fn(move |req| {
                handle_request(req, Arc::clone(&frame_store))
            }))
        }
    });

    // Get the local IP address
    let local_ip = local_ip().unwrap();
    let addr = (local_ip, 5000).into();

    let server = Server::bind(&addr).serve(make_svc);

    println!("Server running on http://{}", addr);

    if let Err(e) = server.await {
        eprintln!("Server error: {}", e);
    }
}

async fn handle_request(
    req: Request<Body>,
    frame_store: FrameStore,
) -> Result<Response<Body>, hyper::Error> {
    match (req.method(), req.uri().path()) {
        (&Method::POST, "/video_stream") => {
            let whole_body = hyper::body::to_bytes(req.into_body()).await?;
            let frame_data: FrameData = serde_json::from_slice(&whole_body).unwrap();
            let frame_bytes = decode(&frame_data.frame).unwrap();

            let mut store = frame_store.lock().unwrap();
            store.insert(frame_data.camera_id, frame_bytes);

            Ok(Response::new(Body::from("Frame received")))
        }
        (&Method::GET, path) if path.starts_with("/video/source_") => {
            let source_id = path.trim_start_matches("/video/source_").to_string();

            let store = frame_store.lock().unwrap();
            if let Some(frame) = store.get(&source_id) {
                let response = Response::builder()
                    .status(StatusCode::OK)
                    .header("Content-Type", "image/jpeg")
                    .body(Body::from(frame.clone()))
                    .unwrap();
                Ok(response)
            } else {
                let response = Response::builder()
                    .status(StatusCode::NOT_FOUND)
                    .body(Body::from("Not Found"))
                    .unwrap();
                Ok(response)
            }
        }
        (&Method::GET, "/") => {
            let contents = include_str!("../static/index.html");
            let response = Response::builder()
                .status(StatusCode::OK)
                .header("Content-Type", "text/html")
                .body(Body::from(contents))
                .unwrap();
            Ok(response)
        }
        _ => {
            let response = Response::builder()
                .status(StatusCode::NOT_FOUND)
                .body(Body::from("Not Found"))
                .unwrap();
            Ok(response)
        }
    }
}

