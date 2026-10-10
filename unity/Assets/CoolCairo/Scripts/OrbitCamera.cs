using UnityEngine;

namespace CoolCairo
{
    // Orbit / pan / zoom around the district. Middle mouse or Alt+left drags orbit, Q / E rotate,
    // Shift+middle pans, WASD pans, scroll zooms. Left alone for a few seconds, the camera
    // drifts slowly around the district, like a satellite pass; any input stops it.
    public class OrbitCamera : MonoBehaviour
    {
        [SerializeField] DistrictView district;
        [SerializeField] float distance = 2200f;
        [SerializeField] float minDistance = 150f, maxDistance = 5000f;
        [SerializeField] float yaw = 20f, pitch = 55f;
        [SerializeField] float orbitSpeed = 4f, panSpeed = 1.2f, zoomSpeed = 0.12f;
        [SerializeField] float idleSeconds = 6f, driftDegreesPerSecond = 2.5f;
        [SerializeField] float keyTurnDegreesPerSecond = 60f;

        Vector3 _target;
        float _lastInput, _drift;
        Vector3 _lastMouse;

        public bool Drifting => _drift > 0.01f;

        void Start()
        {
            var d = district.Data;
            _target = new Vector3(d.cols * d.blockSize / 2f, 0f, d.rows * d.blockSize / 2f);
            Apply();
        }

        void LateUpdate()
        {
            if (DemoRecorder.Recording)
            {
                // Video footage: no mouse or keys, just the slow idle drift from the start.
                _drift = Mathf.MoveTowards(_drift, 1f, Time.deltaTime * 0.4f);
                yaw += _drift * driftDegreesPerSecond * Time.deltaTime;
                Apply();
                return;
            }
            bool orbit = Input.GetMouseButton(2) && !Input.GetKey(KeyCode.LeftShift)
                         || Input.GetMouseButton(0) && Input.GetKey(KeyCode.LeftAlt);
            if (orbit)
            {
                yaw += Input.GetAxis("Mouse X") * orbitSpeed;
                pitch = Mathf.Clamp(pitch - Input.GetAxis("Mouse Y") * orbitSpeed, 15f, 89f);
            }
            // Keys, for touchpads without a middle button.
            float turn = (Input.GetKey(KeyCode.E) ? 1f : 0f) - (Input.GetKey(KeyCode.Q) ? 1f : 0f);
            yaw += turn * keyTurnDegreesPerSecond * Time.deltaTime;

            var flatRight = Quaternion.Euler(0f, yaw, 0f) * Vector3.right;
            var flatForward = Quaternion.Euler(0f, yaw, 0f) * Vector3.forward;
            float panScale = distance * 0.001f * panSpeed;
            if (Input.GetMouseButton(2) && Input.GetKey(KeyCode.LeftShift))
                _target -= (flatRight * Input.GetAxis("Mouse X") + flatForward * Input.GetAxis("Mouse Y")) * panScale * 20f;
            _target += (flatRight * Input.GetAxis("Horizontal") + flatForward * Input.GetAxis("Vertical"))
                       * panScale * 600f * Time.deltaTime;

            float scroll = Input.mouseScrollDelta.y;
            if (scroll != 0f && !DistrictUI.PointerOverUI)
                distance = Mathf.Clamp(distance * (1f - scroll * zoomSpeed), minDistance, maxDistance);

            // Idle drift: eases in after idleSeconds without input, stops at once on any input.
            if (Input.anyKey || scroll != 0f || (Input.mousePosition - _lastMouse).sqrMagnitude > 4f)
                _lastInput = Time.time;
            _lastMouse = Input.mousePosition;
            bool idle = Time.time - _lastInput > idleSeconds;
            _drift = idle ? Mathf.MoveTowards(_drift, 1f, Time.deltaTime * 0.4f) : 0f;
            yaw += _drift * driftDegreesPerSecond * Time.deltaTime;

            Apply();
        }

        void Apply()
        {
            var rot = Quaternion.Euler(pitch, yaw, 0f);
            transform.SetPositionAndRotation(_target - rot * Vector3.forward * distance, rot);
        }
    }
}
