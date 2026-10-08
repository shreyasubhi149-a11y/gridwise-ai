const CACHE_NAME = "gridwise-ai-v1";

self.addEventListener("install", event => {
    self.skipWaiting();
});

self.addEventListener("activate", event => {
    event.waitUntil(
        self.clients.claim()
    );
});

self.addEventListener("notificationclick", event => {
    const action = event.action;
    const notification = event.notification;
    const data = notification.data || {};
    const alertId = data.alertId;

    notification.close();

    if (!alertId || !action) {
        event.waitUntil(
            self.clients.matchAll({
                type: "window",
                includeUncontrolled: true
            }).then(clients => {
                if (clients.length > 0) {
                    return clients[0].focus();
                }

                return self.clients.openWindow("/");
            })
        );

        return;
    }

    event.waitUntil(
        fetch(`/api/alerts/${alertId}/action`, {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({
                action: action
            })
        })
        .then(() => {
            return self.clients.matchAll({
                type: "window",
                includeUncontrolled: true
            });
        })
        .then(clients => {
            clients.forEach(client => {
                client.postMessage({
                    type: "GRIDWISE_ALERT_ACTION",
                    action: action,
                    alertId: alertId
                });
            });
        })
        .catch(error => {
            console.error("Notification action failed:", error);
        })
    );
});