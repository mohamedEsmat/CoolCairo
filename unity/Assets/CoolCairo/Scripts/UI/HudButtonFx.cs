using UnityEngine;
using UnityEngine.EventSystems;
using UnityEngine.UI;

namespace CoolCairo
{
    // Lights up a HUD button's thin outline while the mouse is over it.
    public class HudButtonFx : MonoBehaviour, IPointerEnterHandler, IPointerExitHandler
    {
        Image _frame;
        Selectable _button;
        float _glow, _target;

        void Awake()
        {
            var t = transform.Find("Frame");
            _frame = t != null ? t.GetComponent<Image>() : null;
            _button = GetComponent<Selectable>();
        }

        public void OnPointerEnter(PointerEventData e) => _target = _button == null || _button.interactable ? 1f : 0f;
        public void OnPointerExit(PointerEventData e) => _target = 0f;

        void OnDisable() { _glow = _target = 0f; Apply(); }

        void Update()
        {
            if (Mathf.Approximately(_glow, _target)) return;
            _glow = Mathf.MoveTowards(_glow, _target, Time.unscaledDeltaTime * 8f);
            Apply();
        }

        void Apply()
        {
            if (_frame != null) _frame.color = Color.Lerp(HudStyle.Chrome, HudStyle.ChromeBright, _glow);
        }
    }
}
