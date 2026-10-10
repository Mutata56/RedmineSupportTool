/* WebSocket-клиент /ws/events: авто-переподключение с нарастающей паузой (1..10с).
   Обработчик сообщений отдаёт Alpine-компонент (app.js -> onWsMessage). */
(function () {
    "use strict";

    window.startWS = function (handler) {
        let delay = 1000;
        let sock = null;

        function connect() {
            const proto = location.protocol === "https:" ? "wss" : "ws";
            try {
                sock = new WebSocket(proto + "://" + location.host + "/ws/events");
            } catch (e) {
                return schedule();
            }
            sock.onopen = function () {
                delay = 1000;
                handler.onWsState(true);
            };
            sock.onmessage = function (ev) {
                let msg;
                try { msg = JSON.parse(ev.data); } catch (e) { return; }
                if (msg && msg.type) handler.onWsMessage(msg);
            };
            sock.onclose = function () {
                handler.onWsState(false);
                schedule();
            };
            sock.onerror = function () {
                try { sock.close(); } catch (e) { /* noop */ }
            };
        }

        function schedule() {
            setTimeout(connect, delay);
            delay = Math.min(delay * 1.7, 10000);
        }

        connect();
        return { send: (o) => { try { sock.send(JSON.stringify(o)); } catch (e) { /* noop */ } } };
    };
})();
