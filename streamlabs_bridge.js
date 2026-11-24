(() => {
  const visibleStatus = document.getElementById("status");
  const visibleLast = document.getElementById("last");

  const bridgeId =
    (window.crypto && crypto.randomUUID)
      ? crypto.randomUUID()
      : (
          "bridge-" +
          Date.now() +
          "-" +
          Math.random().toString(36).slice(2)
        );

  let socket = null;
  let activeToken = "";
  let configEnabled = false;
  let currentlyConnected = false;
  let currentState = "starting";
  let currentError = "";
  let reconnectTimer = null;
  let heartbeatTimer = null;
  let configTimer = null;

  function setVisible(text, cls="") {
    if (visibleStatus) {
      visibleStatus.textContent = text;
      visibleStatus.className = cls;
    }
  }

  async function reportStatus(
    state = currentState,
    connected = currentlyConnected,
    error = currentError
  ) {
    currentState = state;
    currentlyConnected = Boolean(connected);
    currentError = String(error || "");

    try {
      await fetch(
        "/api/integrations/streamlabs-status",
        {
          method: "POST",
          headers: {
            "Content-Type":"application/json"
          },
          body: JSON.stringify({
            bridgeId,
            state: currentState,
            connected: currentlyConnected,
            error: currentError
          })
        }
      );
    } catch {}
  }

  async function forwardEvent(eventData) {
    if (visibleLast) {
      visibleLast.textContent =
        JSON.stringify(eventData, null, 2);
    }

    try {
      await fetch(
        "/api/integrations/streamlabs-event",
        {
          method: "POST",
          headers: {
            "Content-Type":"application/json"
          },
          body: JSON.stringify({
            event:eventData
          })
        }
      );
    } catch (error) {
      console.warn(
        "[Streamlabs Bridge] No se pudo reenviar evento:",
        error
      );
    }
  }

  function destroySocket() {
    if (!socket) return;

    try {
      socket.removeAllListeners();
    } catch {}

    try {
      socket.disconnect();
    } catch {}

    socket = null;
    currentlyConnected = false;
  }

  function scheduleHardReconnect(delay = 1800) {
    clearTimeout(reconnectTimer);

    reconnectTimer = setTimeout(
      () => {
        if (
          configEnabled &&
          activeToken
        ) {
          destroySocket();
          connect(activeToken);
        }
      },
      delay
    );
  }

  function connect(token) {
    if (!configEnabled || !token) {
      return;
    }

    if (!window.io) {
      setVisible(
        "❌ No se pudo cargar Socket.IO.",
        "bad"
      );

      reportStatus(
        "socketio_library_error",
        false,
        "No se pudo cargar Socket.IO 2.0.3 desde cdnjs."
      );

      return;
    }

    destroySocket();
    activeToken = token;

    setVisible(
      "🟡 Conectando con Streamlabs...",
      "warn"
    );

    reportStatus(
      "connecting",
      false,
      ""
    );

    socket = window.io(
      `https://sockets.streamlabs.com?token=${encodeURIComponent(token)}`,
      {
        transports: ["websocket"],
        reconnection: true,
        reconnectionAttempts: Infinity,
        reconnectionDelay: 1000,
        reconnectionDelayMax: 5000,
        randomizationFactor: 0.35,
        timeout: 20000,
        forceNew: true
      }
    );

    socket.on("connect", () => {
      setVisible(
        "🟢 Streamlabs conectado",
        "ok"
      );

      reportStatus(
        "connected",
        true,
        ""
      );
    });

    socket.on("event", (eventData) => {
      forwardEvent(eventData);
    });

    socket.on("connect_error", (error) => {
      const text =
        error && error.message
          ? error.message
          : String(
              error || "connect_error"
            );

      setVisible(
        "🟠 Reconectando: " + text,
        "warn"
      );

      reportStatus(
        "connecting",
        false,
        text
      );
    });

    socket.on("connect_timeout", () => {
      setVisible(
        "🟠 Timeout; reconectando...",
        "warn"
      );

      reportStatus(
        "connecting",
        false,
        "Tiempo de conexión agotado"
      );
    });

    socket.on("disconnect", (reason) => {
      currentlyConnected = false;

      setVisible(
        "🟠 Desconectado temporalmente: " + reason,
        "warn"
      );

      reportStatus(
        "connecting",
        false,
        String(reason || "")
      );

      /*
        Socket.IO no se reconecta solo cuando el servidor ordena
        explícitamente la desconexión. Forzamos una nueva sesión.
      */
      if (reason === "io server disconnect") {
        scheduleHardReconnect(1200);
      }
    });

    socket.on("reconnect_attempt", () => {
      setVisible(
        "🟡 Reconectando...",
        "warn"
      );

      reportStatus(
        "connecting",
        false,
        ""
      );
    });

    socket.on("reconnect", () => {
      setVisible(
        "🟢 Streamlabs reconectado",
        "ok"
      );

      reportStatus(
        "connected",
        true,
        ""
      );
    });

    socket.on("reconnect_failed", () => {
      /*
        Con Infinity no debería ocurrir, pero dejamos un watchdog.
      */
      setVisible(
        "🟠 Reiniciando conexión...",
        "warn"
      );

      reportStatus(
        "connecting",
        false,
        "Socket.IO agotó su ciclo de reconexión"
      );

      scheduleHardReconnect(1500);
    });

    socket.on("error", (error) => {
      const text =
        error && error.message
          ? error.message
          : String(
              error || "Socket error"
            );

      console.warn(
        "[Streamlabs Bridge]",
        error
      );

      currentError = text;
    });
  }

  async function refreshConfig() {
    try {
      const response = await fetch(
        "/api/integrations/streamlabs-token",
        {
          cache:"no-store"
        }
      );

      const data = await response.json();

      configEnabled = Boolean(
        data.enabled
      );

      if (!configEnabled) {
        activeToken = "";
        destroySocket();

        setVisible(
          "⚪ Streamlabs deshabilitado",
          ""
        );

        reportStatus(
          "disabled",
          false,
          ""
        );

        return;
      }

      const token = String(
        data.socketToken || ""
      ).trim();

      if (!token) {
        activeToken = "";
        destroySocket();

        setVisible(
          "🔴 Falta Socket API Token",
          "bad"
        );

        reportStatus(
          "missing_token",
          false,
          "Pega el Socket API Token en Integraciones."
        );

        return;
      }

      const socketAlive =
        socket &&
        socket.connected === true;

      if (
        token !== activeToken ||
        !socket ||
        (
          !socketAlive &&
          currentState !== "connecting"
        )
      ) {
        connect(token);
      }
    } catch (error) {
      const text =
        error && error.message
          ? error.message
          : String(error);

      setVisible(
        "🔴 No se pudo leer la configuración local",
        "bad"
      );

      reportStatus(
        "local_server_error",
        false,
        text
      );
    }
  }

  /*
    Heartbeat local:
    aunque Streamlabs no mande eventos durante horas, el servidor sabe
    que esta instancia del bridge sigue viva.
  */
  heartbeatTimer = setInterval(
    () => {
      reportStatus(
        currentlyConnected
          ? "connected"
          : currentState,
        currentlyConnected,
        currentError
      );
    },
    5000
  );

  configTimer = setInterval(
    refreshConfig,
    7000
  );

  window.addEventListener(
    "online",
    () => {
      refreshConfig();

      if (
        configEnabled &&
        activeToken &&
        (
          !socket ||
          !socket.connected
        )
      ) {
        scheduleHardReconnect(300);
      }
    }
  );

  document.addEventListener(
    "visibilitychange",
    () => {
      if (
        !document.hidden &&
        configEnabled &&
        activeToken &&
        (
          !socket ||
          !socket.connected
        )
      ) {
        scheduleHardReconnect(300);
      }
    }
  );

  window.addEventListener(
    "pageshow",
    () => {
      refreshConfig();
    }
  );

  window.addEventListener(
    "beforeunload",
    () => {
      try {
        navigator.sendBeacon(
          "/api/integrations/streamlabs-status",
          new Blob(
            [
              JSON.stringify({
                bridgeId,
                state:"closed",
                connected:false,
                error:""
              })
            ],
            {
              type:"application/json"
            }
          )
        );
      } catch {}
    }
  );

  refreshConfig();
})();