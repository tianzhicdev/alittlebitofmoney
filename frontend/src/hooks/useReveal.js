import { useEffect, useRef } from 'react';

export function useReveal(dependencies = []) {
  const scopeRef = useRef(null);

  useEffect(() => {
    const scope = scopeRef.current;
    if (!scope) {
      return undefined;
    }

    const revealNodes = Array.from(scope.querySelectorAll('.reveal')).filter(
      (node) => node.dataset.revealInit !== '1'
    );
    if (!revealNodes.length) {
      return undefined;
    }

    const revealImmediately = () => {
      revealNodes.forEach((node) => {
        node.dataset.revealInit = '1';
        node.style.opacity = '1';
        node.style.transform = 'none';
        node.style.visibility = 'visible';
      });
    };

    if (!window.gsap || !window.ScrollTrigger) {
      revealImmediately();
      return undefined;
    }

    const gsap = window.gsap;
    const ScrollTrigger = window.ScrollTrigger;

    try {
      gsap.registerPlugin(ScrollTrigger);
    } catch {
      revealImmediately();
      return undefined;
    }

    const viewportCutoff = window.innerHeight * 0.98;

    let animations;
    try {
      animations = revealNodes.map((node, index) => {
        const baseAnimation = {
          autoAlpha: 1,
          y: 0,
          duration: 0.85,
          ease: 'power2.out',
          delay: index * 0.03,
          onComplete: () => {
            node.dataset.revealInit = '1';
          },
        };

        if (node.getBoundingClientRect().top <= viewportCutoff) {
          return gsap.fromTo(node, { autoAlpha: 0, y: 26 }, baseAnimation);
        }

        return gsap.fromTo(
          node,
          { autoAlpha: 0, y: 26 },
          {
            ...baseAnimation,
            scrollTrigger: {
              trigger: node,
              start: 'top 85%',
              once: true,
            },
          }
        );
      });
    } catch {
      revealImmediately();
      return undefined;
    }

    return () => {
      animations.forEach((animation) => {
        if (animation.scrollTrigger) {
          animation.scrollTrigger.kill();
        }
        animation.kill();
      });
      revealNodes.forEach((node) => {
        if (node.dataset.revealInit !== '1') {
          node.style.removeProperty('opacity');
          node.style.removeProperty('transform');
          node.style.removeProperty('visibility');
        }
      });
    };
  }, dependencies);

  return scopeRef;
}
