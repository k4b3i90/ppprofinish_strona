const revealElements = document.querySelectorAll(".reveal");
const form = document.querySelector(".contact-form");
const toast = document.querySelector(".toast");
const submitButton = form?.querySelector('button[type="submit"]');

const showToast = (message) => {
  if (!toast) return;

  toast.textContent = message;
  toast.classList.add("is-visible");

  window.clearTimeout(showToast.timeoutId);
  showToast.timeoutId = window.setTimeout(() => {
    toast.classList.remove("is-visible");
  }, 3200);
};

if ("IntersectionObserver" in window) {
  const observer = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        entry.target.classList.add("is-visible");
        observer.unobserve(entry.target);
      });
    },
    {
      threshold: 0.2,
    }
  );

  revealElements.forEach((element) => observer.observe(element));
} else {
  revealElements.forEach((element) => element.classList.add("is-visible"));
}

if (form) {
  form.addEventListener("submit", async (event) => {
    event.preventDefault();

    const formData = new FormData(form);
    const payload = Object.fromEntries(formData.entries());

    if (submitButton) {
      submitButton.disabled = true;
      submitButton.textContent = "Wysyłanie...";
    }

    try {
      const response = await fetch("/api/contact", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(payload),
      });

      const result = await response.json();

      if (!response.ok) {
        throw new Error(result.error || "Nie udało się wysłać formularza.");
      }

      showToast("Wiadomość została wysłana. Dziękujemy za kontakt.");
      form.reset();
    } catch (error) {
      showToast(error.message || "Wystąpił problem przy wysyłce formularza.");
    } finally {
      if (submitButton) {
        submitButton.disabled = false;
        submitButton.textContent = "Wyślij zapytanie";
      }
    }
  });
}
