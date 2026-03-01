use serde::ser::SerializeStruct;
use serde::{Serialize, Serializer};
use thiserror::Error;

#[derive(Debug, Error)]
pub enum AppError {
    #[error("File not found: {path}")]
    FileNotFound { path: String, code: u32 },
    #[error("Invalid file type: {file_type}")]
    InvalidFileType { file_type: String, code: u32 },
    #[error("OCR failed: {reason}")]
    OcrFailed { reason: String, code: u32 },
    #[error("Validation failed: {details}")]
    ValidationFailed { details: String, code: u32 },
    #[error("Export failed: {reason}")]
    ExportFailed { reason: String, code: u32 },
    #[error("Internal error: {message}")]
    Internal { message: String, code: u32 },
}

impl AppError {
    pub fn error_code(&self) -> u32 {
        match self {
            Self::FileNotFound { code, .. }
            | Self::InvalidFileType { code, .. }
            | Self::OcrFailed { code, .. }
            | Self::ValidationFailed { code, .. }
            | Self::ExportFailed { code, .. }
            | Self::Internal { code, .. } => *code,
        }
    }

    pub fn kind(&self) -> &'static str {
        match self {
            Self::FileNotFound { .. } => "FileNotFound",
            Self::InvalidFileType { .. } => "InvalidFileType",
            Self::OcrFailed { .. } => "OcrFailed",
            Self::ValidationFailed { .. } => "ValidationFailed",
            Self::ExportFailed { .. } => "ExportFailed",
            Self::Internal { .. } => "Internal",
        }
    }
}

impl Serialize for AppError {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        let mut state = serializer.serialize_struct("AppError", 3)?;
        state.serialize_field("message", &self.to_string())?;
        state.serialize_field("code", &self.error_code())?;
        state.serialize_field("kind", &self.kind())?;
        state.end()
    }
}
