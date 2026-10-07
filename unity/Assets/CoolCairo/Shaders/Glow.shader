// Unlit, transparent, vertex-coloured: the paint flash over freshly cooled blocks and the
// heat shimmer over the hottest ones.
//   Flat flash quads: uv0 = uv1 = 0, drawn where they are.
//   Shimmer plumes: all four corners sit at the block centre; uv0 = (1, height 0..1) and
//   uv1 = (sideways offset in m, plume height in m). The vertex shader turns each plume to face
//   the camera, sways it like hot air and the fragment shader fades it to the top and sides.
Shader "CoolCairo/Glow"
{
    Properties
    {
        _Sway ("Sway (m at the top)", Float) = 5
    }
    SubShader
    {
        Tags { "RenderType" = "Transparent" "Queue" = "Transparent" "RenderPipeline" = "UniversalPipeline" }
        Blend SrcAlpha One   // Additive-ish: glows on dark and on light ground
        ZWrite Off
        Cull Off

        Pass
        {
            Name "Unlit"
            Tags { "LightMode" = "UniversalForward" }

            HLSLPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Core.hlsl"

            CBUFFER_START(UnityPerMaterial)
                float _Sway;
            CBUFFER_END

            struct Attributes
            {
                float4 positionOS : POSITION;
                float4 color : COLOR;
                float2 uv : TEXCOORD0;
                float2 plume : TEXCOORD1;
            };
            struct Varyings
            {
                float4 positionCS : SV_POSITION;
                half4 color : COLOR;
                float2 uv : TEXCOORD0;
                float side : TEXCOORD1;
            };

            Varyings vert(Attributes input)
            {
                Varyings o;
                float3 world = TransformObjectToWorld(input.positionOS.xyz);
                float h = input.uv.y;
                float3 right = normalize(float3(UNITY_MATRIX_V[0].x, 0, UNITY_MATRIX_V[0].z) + 1e-5);
                world += right * input.plume.x + float3(0, 1, 0) * input.plume.y * h;
                // Hot air: a slow sideways wave, stronger higher up, out of phase between blocks.
                float t = _Time.y;
                world.x += sin(t * 1.7 + world.z * 0.05 + h * 4.0) * _Sway * h;
                world.z += cos(t * 1.3 + world.x * 0.04 + h * 3.0) * _Sway * 0.6 * h;
                o.positionCS = TransformWorldToHClip(world);
                o.color = input.color;
                o.uv = input.uv;
                o.side = input.plume.x == 0 ? 0 : sign(input.plume.x);
                return o;
            }

            half4 frag(Varyings input) : SV_Target
            {
                half4 c = input.color;
                float h = input.uv.y;
                // Plumes: soft sides, fade towards the top, faint bands drifting upwards.
                half rise = 0.75 + 0.25 * sin((h * 5.0 - _Time.y * 1.5) * 3.14159);
                half soft = 1.0 - input.side * input.side;
                half plume = soft * pow(saturate(1.0 - h), 1.5) * rise;
                return half4(c.rgb, c.a * lerp(1.0, plume, input.uv.x));
            }
            ENDHLSL
        }
    }
}
