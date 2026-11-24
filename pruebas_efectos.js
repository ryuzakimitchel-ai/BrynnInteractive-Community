const statusEl = document.getElementById("status");

async function trigger(effect) {
    statusEl.textContent = "Enviando prueba: " + effect + "...";

    try {
        const response = await fetch("/api/test-effect", {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({ effect })
        });

        const data = await response.json();

        if (!response.ok || !data.ok) {
            throw new Error(data.error || ("HTTP " + response.status));
        }

        statusEl.textContent =
            "✅ Evento enviado. Mira el overlay de eventos en OBS.";
    }
    catch (error) {
        statusEl.textContent =
            "❌ No se pudo enviar la prueba: " + error.message;
    }
}

document.querySelectorAll("[data-effect]").forEach(button => {
    button.addEventListener("click", () => {
        trigger(button.dataset.effect);
    });
});
