mod commands;
mod error;
mod export;
mod models;
mod ocr;
mod state;
mod validation;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_dialog::init())
        .manage(state::AppState::default())
        .invoke_handler(tauri::generate_handler![
            commands::import_files,
            commands::get_processing_status,
            commands::get_all_rows,
            commands::get_row_detail,
            commands::update_field,
            commands::set_row_status,
            commands::rerun_extraction,
            commands::export_excel_command,
            commands::run_ocr_for_row,
            commands::save_memory_entry
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
