using System.Collections;
using TMPro;
using UnityEngine;
using UnityEngine.UI;

namespace CoolCairo
{
    // The HUD's constant small motion, so the screen reads as a live feed rather than a static
    // page: panels slide in on arrival, a scan line sweeps the map, "SAT LINK" blinks, the UTC
    // clock ticks and the data sources scroll past along the bottom. Also slides popups in.
    public class HudMotion : MonoBehaviour
    {
        const float TickerSpeed = 55f;              // canvas px per second
        const float ScanSeconds = 7f, ScanPause = 2.5f;
        const string TickerGap = "      ◆      ";

        RectTransform _canvas, _scan, _ticker;
        Image _dot;
        TextMeshProUGUI _clock, _tickerText;
        float _tickerWidth, _tickerX;
        int _clockSecond = -1;

        void Awake()
        {
            _canvas = (RectTransform)transform;
            _scan = Find(HudStyle.ScanLine);
            _dot = Find(HudStyle.LinkDot)?.GetComponent<Image>();
            _clock = Find(HudStyle.Clock)?.GetComponent<TextMeshProUGUI>();
            _ticker = Find(HudStyle.Footer);
            _tickerText = _ticker?.GetComponent<TextMeshProUGUI>();
        }

        void Start()
        {
            // Arrival: each panel slides in from its own edge and fades up, one after another.
            Arrive(HudStyle.TopBar, new Vector2(0, 40), 0.00f);
            Arrive(HudStyle.Sidebar, new Vector2(-60, 0), 0.08f);
            Arrive(HudStyle.Kpis, new Vector2(60, 0), 0.16f);
            Arrive(HudStyle.Dock, new Vector2(0, -60), 0.24f);
            Arrive(HudStyle.Legend, new Vector2(60, 0), 0.32f);
            Arrive(HudStyle.Ticker, new Vector2(0, -30), 0.40f);
        }

        // The ticker shows the text twice in a row, so it can wrap around without a jump.
        public void SetTicker(string text)
        {
            if (_tickerText == null) return;
            _tickerText.text = text + TickerGap;
            _tickerWidth = _tickerText.GetPreferredValues().x;
            _tickerText.text = text + TickerGap + text + TickerGap;
            _ticker.sizeDelta = new Vector2(_tickerWidth * 2f + 20f, _ticker.sizeDelta.y);
            _tickerX = 0f;
        }

        public string TickerText => _tickerText != null ? _tickerText.text : "";

        void Update()
        {
            float t = Time.unscaledTime;

            if (_scan != null)
            {
                float cycle = (t % (ScanSeconds + ScanPause)) / ScanSeconds;
                float h = _canvas.rect.height + 200f;
                _scan.anchoredPosition = new Vector2(0f, cycle <= 1f ? -cycle * h + 100f : 200f);
            }

            if (_dot != null)
            {
                // A steady pulse, with a quick double blink every few seconds ("packet received").
                float pulse = 0.55f + 0.45f * Mathf.Sin(t * 3.2f);
                float p = t % 4.2f;
                if (p < 0.08f || (p > 0.16f && p < 0.24f)) pulse = 0.15f;
                var c = _dot.color;
                c.a = pulse;
                _dot.color = c;
            }

            if (_clock != null)
            {
                var now = System.DateTime.UtcNow;
                if (now.Second != _clockSecond)
                {
                    _clockSecond = now.Second;
                    _clock.text = $"UTC {now:HH:mm:ss}";
                }
            }

            if (_ticker != null && _tickerWidth > 0f)
            {
                _tickerX -= TickerSpeed * Time.unscaledDeltaTime;
                if (_tickerX <= -_tickerWidth) _tickerX += _tickerWidth;
                _ticker.anchoredPosition = new Vector2(_tickerX, 0f);
            }
        }

        // ---------- one-off animations ----------

        // Slide a popup card up into place while its dimmed backdrop fades in.
        public void PopIn(RectTransform card, CanvasGroup backdrop) => StartCoroutine(PopRoutine(card, backdrop));

        IEnumerator PopRoutine(RectTransform card, CanvasGroup backdrop)
        {
            const float seconds = 0.28f;
            var home = Vector2.zero;
            for (float a = 0f; a < 1f; a += Time.unscaledDeltaTime / seconds)
            {
                float e = 1f - Mathf.Pow(1f - a, 3f);
                card.anchoredPosition = home + new Vector2(0f, -50f * (1f - e));
                card.localScale = Vector3.one * Mathf.Lerp(0.97f, 1f, e);
                if (backdrop != null) backdrop.alpha = e;
                yield return null;
            }
            card.anchoredPosition = home;
            card.localScale = Vector3.one;
            if (backdrop != null) backdrop.alpha = 1f;
        }

        void Arrive(string name, Vector2 from, float delay)
        {
            var rt = Find(name);
            if (rt != null) StartCoroutine(ArriveRoutine(rt, from, delay));
        }

        IEnumerator ArriveRoutine(RectTransform rt, Vector2 from, float delay)
        {
            var group = rt.GetComponent<CanvasGroup>();   // explicit check: ?? misses Unity's fake null
            if (group == null) group = rt.gameObject.AddComponent<CanvasGroup>();
            var home = rt.anchoredPosition;
            group.alpha = 0f;
            rt.anchoredPosition = home + from;
            for (float w = 0f; w < delay; w += Time.unscaledDeltaTime) yield return null;
            const float seconds = 0.45f;
            for (float a = 0f; a < 1f; a += Time.unscaledDeltaTime / seconds)
            {
                float e = 1f - Mathf.Pow(1f - a, 3f);
                rt.anchoredPosition = home + from * (1f - e);
                // A short flicker as the panel "powers on".
                group.alpha = a < 0.3f ? (Mathf.Repeat(a * 20f, 1f) < 0.5f ? 0.3f : 0.8f) * e : e;
                yield return null;
            }
            rt.anchoredPosition = home;
            group.alpha = 1f;
        }

        RectTransform Find(string name)
        {
            foreach (var t in GetComponentsInChildren<RectTransform>(true))
                if (t.name == name) return t;
            return null;
        }
    }
}
