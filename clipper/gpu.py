"""Make pip-installed NVIDIA libraries (nvidia-cublas-cu12, nvidia-cudnn-cu12)
loadable by ctranslate2/faster-whisper without relying on LD_LIBRARY_PATH:
preload every .so under site-packages/nvidia/*/lib with RTLD_GLOBAL."""
import ctypes, glob, os, site

_done = False


def preload_cuda():
    global _done
    if _done:
        return []
    _done = True
    libs = []
    for sp in site.getsitepackages() + [site.getusersitepackages()]:
        libs += glob.glob(os.path.join(sp, "nvidia", "*", "lib", "*.so*"))
    pending, loaded = sorted(set(libs)), []
    # several passes so libraries load after their dependencies
    for _ in range(4):
        failed = []
        for path in pending:
            try:
                ctypes.CDLL(path, mode=ctypes.RTLD_GLOBAL)
                loaded.append(os.path.basename(path))
            except OSError:
                failed.append(path)
        if not failed or len(failed) == len(pending):
            pending = failed
            break
        pending = failed
    return loaded


if __name__ == "__main__":
    got = preload_cuda()
    print(f"preloaded {len(got)} libs:", ", ".join(x for x in got if "cublas" in x or "cudnn.so" in x))
