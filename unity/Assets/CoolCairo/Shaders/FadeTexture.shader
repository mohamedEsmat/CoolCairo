// Unlit transparent texture with a global fade and soft edges: the Sentinel-2 close-up that
// blends in over the globe during the fly-in, without a visible rectangle border.
Shader "CoolCairo/FadeTexture"
{
    Properties
    {
        _BaseMap ("Texture", 2D) = "white" {}
        _Alpha ("Alpha", Range(0, 1)) = 1
        _Edge ("Soft edge width (uv)", Range(0.001, 0.5)) = 0.15
    }
    SubShader
    {
        Tags { "RenderType" = "Transparent" "Queue" = "Transparent" "RenderPipeline" = "UniversalPipeline" }
        Blend SrcAlpha OneMinusSrcAlpha
        ZWrite Off

        Pass
        {
            Name "Unlit"
            Tags { "LightMode" = "UniversalForward" }

            HLSLPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Core.hlsl"

            TEXTURE2D(_BaseMap);
            SAMPLER(sampler_BaseMap);
            CBUFFER_START(UnityPerMaterial)
                float4 _BaseMap_ST;
                half _Alpha;
                half _Edge;
            CBUFFER_END

            struct Attributes { float4 positionOS : POSITION; float2 uv : TEXCOORD0; };
            struct Varyings { float4 positionCS : SV_POSITION; float2 uv : TEXCOORD0; };

            Varyings vert(Attributes input)
            {
                Varyings o;
                o.positionCS = TransformObjectToHClip(input.positionOS.xyz);
                o.uv = input.uv;
                return o;
            }

            half4 frag(Varyings input) : SV_Target
            {
                half4 c = SAMPLE_TEXTURE2D(_BaseMap, sampler_BaseMap, input.uv);
                float2 d = min(input.uv, 1 - input.uv);
                half edge = smoothstep(0, _Edge, d.x) * smoothstep(0, _Edge, d.y);
                return half4(c.rgb, c.a * edge * _Alpha);
            }
            ENDHLSL
        }
    }
}
