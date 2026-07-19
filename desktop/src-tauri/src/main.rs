#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    kestrel_desktop_lib::run();
}
