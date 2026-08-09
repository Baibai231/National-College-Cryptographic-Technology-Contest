// Anti-bot-detection countermeasures running in the browser context.
// Converted from module.exports to IIFE for CDP injection via
// Page.addScriptToEvaluateOnNewDocument.

(function() {
    if (window.Notification && Notification.permission === 'denied') {
        Reflect.defineProperty(window.Notification, 'permission', {get: function() { return 'default'; }});
    }

    if (window.Navigator) {
        Reflect.defineProperty(window.Navigator.prototype, 'webdriver', {get: function() { return undefined; }});
    }

    if (!window.chrome || !window.chrome.runtime) {
        window.chrome = {
            "app": {
                "isInstalled": false,
                "InstallState": {"DISABLED": "disabled", "INSTALLED": "installed", "NOT_INSTALLED": "not_installed"},
                "RunningState": {"CANNOT_RUN": "cannot_run", "READY_TO_RUN": "ready_to_run", "RUNNING": "running"}
            },
            "runtime": {
                "OnInstalledReason": {"CHROME_UPDATE": "chrome_update", "INSTALL": "install", "SHARED_MODULE_UPDATE": "shared_module_update", "UPDATE": "update"},
                "OnRestartRequiredReason": {"APP_UPDATE": "app_update", "OS_UPDATE": "os_update", "PERIODIC": "periodic"},
                "PlatformArch": {"ARM": "arm", "ARM64": "arm64", "MIPS": "mips", "MIPS64": "mips64", "X86_32": "x86-32", "X86_64": "x86-64"},
                "PlatformNaclArch": {"ARM": "arm", "MIPS": "mips", "MIPS64": "mips64", "X86_32": "x86-32", "X86_64": "x86-64"},
                "PlatformOs": {"ANDROID": "android", "CROS": "cros", "LINUX": "linux", "MAC": "mac", "OPENBSD": "openbsd", "WIN": "win"},
                "RequestUpdateCheckStatus": {
                    "NO_UPDATE": "no_update", "THROTTLED": "throttled", "UPDATE_AVAILABLE": "update_available"
                }
            }
        };
    }

    if (window.Navigator && window.navigator.plugins.length === 0) {
        Reflect.defineProperty(window.Navigator.prototype, 'plugins', {
            get: function() {
                return [{
                    description: "Portable Document Format",
                    filename: "internal-pdf-viewer",
                    name: "Chrome PDF Plugin",
                    0: {type: "application/pdf"}
                }];
            }
        });
    }
})();
