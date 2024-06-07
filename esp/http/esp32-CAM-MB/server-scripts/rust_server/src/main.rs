use actix_files::NamedFile;
use actix_web::{get, post, web, App, HttpResponse, HttpServer, Responder};
use futures::StreamExt;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::sync::{Arc, Mutex};
use tokio::sync::broadcast;
use async_stream::stream;
use base64::decode;

#[derive(Deserialize)]
struct FrameData {
    camera_id: String,
    frame: String,
}

struct AppState {
    frames: Mutex<HashMap<String, Vec<u8>>>,
    tx: broadcast::Sender<(String, Vec<u8>)>,
}

#[get("/frame/{camera_id}")]
async fn get_frame(data: web::Data<AppState>, path: web::Path<String>) -> impl Responder {
    let camera_id = path.into_inner();
    println!("Client connected for frame stream: {}", camera_id);
    let mut rx = data.tx.subscribe();
    let stream = stream! {
        while let Ok((id, frame)) = rx.recv().await {
            if id == camera_id {
                yield Ok::<_, actix_web::Error>(actix_web::web::Bytes::from(frame));
            }
        }
    };
    HttpResponse::Ok()
        .content_type("image/jpeg")
        .streaming(stream)
}

#[post("/video_stream")]
async fn update_frame(data: web::Data<AppState>, json: web::Json<FrameData>) -> impl Responder {
    println!("Received new frame from camera: {}", json.camera_id);
    let frame_data = match decode(&json.frame) {
        Ok(data) => data,
        Err(_) => return HttpResponse::BadRequest().body("Invalid base64 data"),
    };

    let mut frames = data.frames.lock().unwrap();
    frames.insert(json.camera_id.clone(), frame_data.clone());
    let _ = data.tx.send((json.camera_id.clone(), frame_data));
    HttpResponse::Ok().body("Frame updated")
}

#[get("/")]
async fn index() -> impl Responder {
    NamedFile::open_async("./static/index.html").await
}

#[actix_web::main]
async fn main() -> std::io::Result<()> {
    // Initialize shared state
    let (tx, _rx) = broadcast::channel(16);
    let app_data = web::Data::new(AppState {
        frames: Mutex::new(HashMap::new()),
        tx,
    });

    // Start HTTP server
    HttpServer::new(move || {
        App::new()
            .app_data(app_data.clone())
            .service(get_frame)
            .service(update_frame)
            .service(index)
            .service(actix_files::Files::new("/static", "./static").show_files_listing())
    })
    .bind("0.0.0.0:5000")?
    .run()
    .await
}

    // Configure SSL
    //let mut builder = SslAcceptor::mozilla_intermediate(SslMethod::tls()).unwrap();
    //builder.set_private_key_file("key.pem", SslFiletype::PEM).unwrap();
    //builder.set_certificate_chain_file("cert.pem").unwrap();
    //.bind_openssl("127.0.0.1:8443", builder)?
