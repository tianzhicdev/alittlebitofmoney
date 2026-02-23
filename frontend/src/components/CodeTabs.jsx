import { useEffect, useState } from 'react';
import CodeBlock from './CodeBlock';

export default function CodeTabs({ tabs }) {
  const [activeIndex, setActiveIndex] = useState(0);

  useEffect(() => {
    setActiveIndex(0);
  }, [tabs]);

  if (!tabs?.length) {
    return null;
  }

  const activeTab = tabs[activeIndex] || tabs[0];

  return (
    <div>
      <div className="code-tabs">
        {tabs.map((tab, index) => (
          <button
            key={`${tab.label}-${index}`}
            type="button"
            className={`code-tab ${index === activeIndex ? 'active' : ''}`.trim()}
            onClick={() => setActiveIndex(index)}
          >
            {tab.label}
          </button>
        ))}
      </div>
      <CodeBlock code={activeTab.code} language={activeTab.language || activeTab.label} />
    </div>
  );
}
