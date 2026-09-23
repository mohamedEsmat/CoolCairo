using UnityEngine;

namespace CoolCairo
{
    // Orbit / pan / zoom around the district. Middle mouse or Alt+left drags orbit,
    // Shift+middle pans, WASD pans, scroll zooms.
    public class OrbitCamera : MonoBehaviour
    {
        [SerializeField] DistrictView district;
        [SerializeField] float distance = 2200f;
        [SerializeField] float minDistance = 150f, maxDistance = 5000f;
        [SerializeField] float yaw = 20f, pitch = 55f;
        [SerializeField] float orbitSpeed = 4f, panSpeed = 1.2f, zoomSpeed = 0.12f;

        Vector3 _target;

        void Start()
        {
            var d = district.Data;
            _target = new Vector3(d.cols * d.blockSize / 2f, 0f, d.rows * d.blockSize / 2f);
            Apply();
        }

        void LateUpdate()
        {
            bool orbit = Input.GetMouseButton(2) && !Input.GetKey(KeyCode.LeftShift)
                         || Input.GetMouseButton(0) && Input.GetKey(KeyCode.LeftAlt);
            if (orbit)
            {
                yaw += Input.GetAxis("Mouse X") * orbitSpeed;
                pitch = Mathf.Clamp(pitch - Input.GetAxis("Mouse Y") * orbitSpeed, 15f, 89f);
            }

            var flatRight = Quaternion.Euler(0f, yaw, 0f) * Vector3.right;
            var flatForward = Quaternion.Euler(0f, yaw, 0f) * Vector3.forward;
            float panScale = distance * 0.001f * panSpeed;
            if (Input.GetMouseButton(2) && Input.GetKey(KeyCode.LeftShift))
                _target -= (flatRight * Input.GetAxis("Mouse X") + flatForward * Input.GetAxis("Mouse Y")) * panScale * 20f;
            _target += (flatRight * Input.GetAxis("Horizontal") + flatForward * Input.GetAxis("Vertical"))
                       * panScale * 600f * Time.deltaTime;

            float scroll = Input.mouseScrollDelta.y;
            if (scroll != 0f && !HUD.PointerOverPanel)
                distance = Mathf.Clamp(distance * (1f - scroll * zoomSpeed), minDistance, maxDistance);

            Apply();
        }

        void Apply()
        {
            var rot = Quaternion.Euler(pitch, yaw, 0f);
            transform.SetPositionAndRotation(_target - rot * Vector3.forward * distance, rot);
        }
    }
}
