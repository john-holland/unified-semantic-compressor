# Environment Considerations: Endlines, Endianness, Portability

For the Unified Semantic Archiver and Continuum Cave integration.

## Endlines

- **SQLite**: Stores data in its native format; text is UTF-8. Line endings in stored scripts (TEXT) are preserved as-is. When exporting/importing between Windows (CRLF) and Unix (LF), scripts may need normalization if tools expect a specific format.
- **Python**: Use `open(..., newline='\n')` or `encoding='utf-8'` for consistent behavior. `pathlib.Path.read_text()` uses default encoding; write scripts with `\n` for cross-platform compatibility.
- **.vor exports**: Use LF in manifest.json and script files for maximum portability.

## Endianness (Big / Little Endian)

- **safetensors, VAE, model files**: These formats are typically designed for portability. SafeTensors uses little-endian by default; most ML frameworks and model files (e.g., PyTorch, Diffusers) are little-endian and work across x86, ARM (little-endian), and common platforms.
- **Continuum DB**: SQLite uses the host's native byte order for internal storage but presents a consistent logical view. No endianness concerns for SQLite itself.
- **Binary diffs / blobs**: If storing raw binary diffs, document the byte order. For portability, prefer formats that encode endianness (e.g., standard formats) or use network byte order (big-endian) for multi-platform exchange.
- **Recommendation**: For safetensors, VAEs, and model files used in generative compression, assume little-endian unless the format explicitly specifies otherwise. No special handling should be required for typical use.

## Environment Portability Summary

- **SQLite**: Portable; single file; no special configuration.
- **Python**: Run with UTF-8 (`PYTHONUTF8=1` or `-X utf8` on Python 3.7+).
- **Luigi**: Uses local filesystem; paths should use `pathlib` for cross-platform correctness.
- **Unity**: Editor runs on Windows/Mac/Linux; ensure DB path and Python path work on the target OS.
- **Model files**: SafeTensors, common VAE formats, and typical diffuser checkpoints are portable across environments with the above considerations.
