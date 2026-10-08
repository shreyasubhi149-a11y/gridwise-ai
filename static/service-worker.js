/* global self */

self.addEventListener("install", function (event) {
    self.skipWaiting();
});

self.addEventListener("activate", function (event) {
    event.waitUntil(
        self.clients.claim()
    );
});

self.addEventListener("notificationclick", function (event) {

    var action = event.action;
    var notification = event.notification;
    var data = notification.data || {};
    var alertId = data.alertId;

    notification.close();

    // If there is no alert ID or no button action,
    // simply open/focus GridWise.
    if (!alertId || !action) {

        event.waitUntil(
            self.clients.matchAll({
                type: "window",
                includeUncontrolled: true
            }).then(function (clients) {

                if (clients.length > 0) {
                    return clients[0].focus();
                }

                return self.clients.openWindow("/");
            })
        );

        return;
    }

    // Send the user's notification choice to Flask.
    event.waitUntil(
        fetch("/api/alerts/" + alertId + "/action", {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({
                action: action
            })
        })
        .then(function () {
            return self.clients.matchAll({
                type: "window",
                includeUncontrolled: true
            });
        })
        .then(function (clients) {

            clients.forEach(function (client) {

                client.postMessage({
                    type: "GRIDWISE_ALERT_ACTION",
                    action: action,
                    alertId: alertId
                });

            });

        })
        .catch(function (error) {

            console.error(
                "GridWise notification action failed:",
                error
            );

        })
    );
});