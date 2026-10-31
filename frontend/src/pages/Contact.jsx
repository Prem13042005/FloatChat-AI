import { useState } from "react";
import { Mail, MapPin, Send } from "lucide-react";
import Navbar from "../components/Navbar";
import Footer from "../components/Footer";

export default function Contact() {
  const [form, setForm] = useState({
    name: "",
    email: "",
    subject: "",
    message: "",
  });

  const [status, setStatus] = useState("");

  function handleChange(event) {
    setForm({
      ...form,
      [event.target.name]: event.target.value,
    });
  }

  function handleSubmit(event) {
    event.preventDefault();

    // This is a frontend-only contact form until a contact API is added.
    setStatus(
      "The form is validated, but message delivery is not configured yet."
    );
  }

  return (
    <>
      {/* <Navbar /> */}

      <main className="public-page">
        <section className="page-hero">
          <span className="eyebrow">CONTACT US</span>
          <h1>Let's talk about FloatChat</h1>
          <p>
            Have a question about the platform or its development?
            Use the form to prepare your message.
          </p>
        </section>

        <section className="contact-layout">
          <div className="contact-info">
            <h2>Get in touch</h2>
            <p>
              Share your questions, feedback, or suggestions about
              oceanographic data exploration.
            </p>

            <div className="contact-detail">
              <Mail size={22} />
              <div>
                <strong>Email</strong>
                <p>Configure your project email address here.</p>
              </div>
            </div>

            <div className="contact-detail">
              <MapPin size={22} />
              <div>
                <strong>Project</strong>
                <p>FloatChat — Oceanographic Analytics</p>
              </div>
            </div>
          </div>

          <form className="form-card" onSubmit={handleSubmit}>
            <label>
              Full name
              <input
                name="name"
                value={form.name}
                onChange={handleChange}
                placeholder="Enter your name"
                required
              />
            </label>

            <label>
              Email address
              <input
                type="email"
                name="email"
                value={form.email}
                onChange={handleChange}
                placeholder="you@example.com"
                required
              />
            </label>

            <label>
              Subject
              <input
                name="subject"
                value={form.subject}
                onChange={handleChange}
                placeholder="How can we help?"
                required
              />
            </label>

            <label>
              Message
              <textarea
                name="message"
                value={form.message}
                onChange={handleChange}
                placeholder="Write your message..."
                rows={5}
                required
              />
            </label>

            <button className="button button-primary" type="submit">
              Prepare Message <Send size={17} />
            </button>

            {status && <p className="form-status">{status}</p>}
          </form>
        </section>
      </main>

      <Footer />
    </>
  );
}