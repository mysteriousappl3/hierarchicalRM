Shader "Hidden/ColorDepth"
{
	Properties
	{
		_MainTex("Texture", 2D) = "white"
	}

		SubShader
	{
		Tags {"RenderType" = "Opaque" "RenderPipeline" = "UniversalPipeline"}

		Pass
		{
			HLSLPROGRAM
			#pragma vertex vert
			#pragma fragment frag
			#include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Core.hlsl"

			struct Attributes
			{
				float4 positionOS : POSITION;
				float2 uv : TEXCOORD0;
			};

			struct Varyings
			{
				float4 positionHCS : SV_POSITION;
				float2 uv : TEXCOORD0;
			};

			TEXTURE2D(_MainTex);
			SAMPLER(sampler_MainTex);
			float4 _MainTex_TexelSize;
			float4 _MainTex_ST;

			TEXTURE2D_X_FLOAT(_CameraDepthTexture);
			SAMPLER(sampler_CameraDepthTexture);

			int _BlurStrength;

			float SampleSceneDepth(float2 uv)
			{
				return SAMPLE_TEXTURE2D_X(_CameraDepthTexture, sampler_CameraDepthTexture, uv).r;
			}

			Varyings vert(Attributes IN)
			{
				Varyings OUT;
				OUT.positionHCS = TransformObjectToHClip(IN.positionOS.xyz);
				OUT.uv = TRANSFORM_TEX(IN.uv, _MainTex);
				return OUT;
			}

			half4 frag(Varyings IN) : SV_TARGET
			{
				// Calculate Depth
				float2 UV = IN.positionHCS.xy / _ScaledScreenParams.xy;
				// Sample the depth from the Camera depth texture.
				#if UNITY_REVERSED_Z
					float depth = SampleSceneDepth(UV);
				#else
					// Adjust Z to match NDC for OpenGL ([-1, 1])
					real depth = lerp(UNITY_NEAR_CLIP_VALUE, 1, SampleSceneDepth(UV));
				#endif

				// Set the color to black in the proximity to the far clipping plane.
				#if UNITY_REVERSED_Z
					// Case for platforms with REVERSED_Z, such as D3D.
					if (depth < 0.00001)
						return float4(0, 0, 0, 1);
				#else
				// Case for platforms without REVERSED_Z, such as OpenGL.
					if (depth > 0.99999)
						return float4(0, 0, 0, 1);
				#endif

				
				// float nearClip = _ProjectionParams.z;
                // float farClip = _ProjectionParams.w;
				// float depth01 = depth * UNITY_Z_0_FAR_FROM_CLIPSPACE(farClip);
                // depth01 = 1 - depth01;

				float depth01 = Linear01Depth(depth, _ZBufferParams);
				// float depth01 = depth * _ProjectionParams.z;
				
				// float depth01 = Linear01Depth(depth, _ZBufferParams);

				float4 color = SAMPLE_TEXTURE2D(_MainTex, sampler_MainTex, IN.uv);
				// return float4(color.rgb, depth01);
				return float4(depth01, depth01, depth01, 1);
			}
			ENDHLSL
		}
	}
}