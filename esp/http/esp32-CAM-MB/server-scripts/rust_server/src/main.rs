use actix_web::{get, post, web, App, HttpResponse, HttpServer, Responder};
use futures::StreamExt;
use std::sync::{Arc, Mutex};
use std::time::Duration;
use tokio::sync::broadcast;
use tokio::time::interval;

#[get("/frame")]
async fn get_frame(data: web::Data<AppState>) -> impl Responder {
    println!("Client connected for frame stream");
    let mut rx = data.tx.subscribe();
    let stream = async_stream::stream! {
        while let Ok(frame) = rx.recv().await {
            yield Ok::<_, actix_web::Error>(actix_web::web::Bytes::from(frame));
        }
    };
    HttpResponse::Ok()
        .content_type("image/jpeg")
        .streaming(stream)
}

#[post("/frame")]
async fn update_frame(data: web::Data<AppState>, bytes: web::Bytes) -> impl Responder {
    println!("Received new frame");
    let mut frame = data.frame.lock().unwrap();
    *frame = bytes.to_vec();
    let _ = data.tx.send(frame.clone());
    HttpResponse::Ok().body("Frame updated")
}

struct AppState {
    frame: Mutex<Vec<u8>>,
    tx: broadcast::Sender<Vec<u8>>,
}

#[actix_web::main]
async fn main() -> std::io::Result<()> {
    // Initialize shared state
    let (tx, _rx) = broadcast::channel(16);
    let frame_data = AppState {
        frame: Mutex::new(Vec::new()),
        tx,
    };
    let app_data = web::Data::new(frame_data);

    // Start HTTP server
    HttpServer::new(move || {
        App::new()
            .app_data(app_data.clone())
            .service(get_frame)
            .service(update_frame)
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
