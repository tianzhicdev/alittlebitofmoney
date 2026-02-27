import { useState } from 'react';

export default function FAQ({ items }) {
  const [openIndex, setOpenIndex] = useState(null);

  return (
    <div>
      {items.map((item, index) => {
        const open = openIndex === index;
        return (
          <article key={item.question} className="faq-item">
            <button
              type="button"
              className="faq-button"
              onClick={() => setOpenIndex(open ? null : index)}
              aria-expanded={open}
            >
              {item.question}
            </button>
            {open ? <div className="faq-answer">{item.answer}</div> : null}
          </article>
        );
      })}
    </div>
  );
}
