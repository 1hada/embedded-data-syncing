use warp::Filter;
use crate::mdns_discovery::CameraFinder;

pub async fn start_server(camera_finder: CameraFinder) {
    let camera_finder = warp::any().map(move || camera_finder.clone());

    let routes = warp::path::end()
        .and(camera_finder)
        .map(|camera_finder: CameraFinder| warp::reply::html(get_html(&camera_finder)));

    warp::serve(routes)
        .run(([127, 0, 0, 1], 8080))
        .await;
}

fn get_html(camera_finder: &CameraFinder) -> String {
    let camera_names = ["source_1", "source_2", "source_3", "source_4"];
    let mut table_rows = String::new();

    for chunk in camera_names.chunks(2) {
        let row = format!(
            r#"<tr>
                <td>{}</td>
                <td>{}</td>
            </tr>"#,
            camera_finder.get_camera_url(chunk[0]).unwrap_or_default(),
            camera_finder.get_camera_url(chunk[1]).unwrap_or_default()
        );
        let row = format!(
            r#"<tr>
                <td><iframe src ="{}" width="100%" height="300">
                    <p>Your browser does not support iframes.</p>
                    </iframe></td>
                <td><iframe src ="{}" width="100%" height="300">
                    <p>Your browser does not support iframes.</p>
                    </iframe></td>
            </tr>"#,
            camera_finder.get_camera_url(chunk[0]).unwrap_or_default(),
            camera_finder.get_camera_url(chunk[1]).unwrap_or_default()
        );
        
        table_rows.push_str(&row);
    }

    format!(
        r#"
        <!DOCTYPE html>
        <html>
        <head>
            <title>Camera Streams</title>
            <style>
                table {{
                    width: 100%;
                }}
                td {{
                    padding: 10px;
                    text-align: center;
                }}
                iframe {{
                    width: 100%;
                    height: 300px;
                }}
            </style>
        </head>
        <body>
            <h1>Camera Streams</h1>
            <table border="1">
                {}
            </table>
        </body>
        </html>
        "#,
        table_rows
    )
}
