// This Unity shader reconstructs the world/camera space positions for pixels using a depth
// texture and screen space UV coordinates.
Shader "Custom/URPDepthWorldPos"
{
	Properties
	{ }

		// The SubShader block containing the Shader code.
		SubShader
	{
		// SubShader Tags define when and under which conditions a SubShader block or
		// a pass is executed.
		Tags { "RenderType" = "Opaque" "RenderPipeline" = "UniversalPipeline" }

		Pass
		{

		HLSLPROGRAM
		#pragma vertex vert
		#pragma fragment frag

		#include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Core.hlsl"
		#include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/DeclareDepthTexture.hlsl"

		struct Attributes
		{
			float4 positionOS   : POSITION;
		};

		struct Varyings
		{
			float4 positionHCS  : SV_POSITION;
			float4 positionOS  : TEXTURE0;
		};


		Varyings vert(Attributes IN)
		{
			Varyings OUT;
			OUT.positionHCS = TransformObjectToHClip(IN.positionOS.xyz);
			OUT.positionOS = IN.positionOS;
			return OUT;
		}

		float4 frag(Varyings IN) : SV_Target
		{
			// To calculate the UV coordinates for sampling the depth buffer,
			// divide the pixel location by the render target resolution
			// _ScaledScreenParams.
			float2 UV = IN.positionHCS.xy / _ScaledScreenParams.xy;

			// Sample the depth from the Camera depth texture.
			#if UNITY_REVERSED_Z
				float depth = SampleSceneDepth(UV);
			#else
				// Adjust Z to match NDC for OpenGL ([-1, 1])
				float depth = lerp(0, 1, SampleSceneDepth(UV));
			#endif

			// Set the color to black in the proximity to the far clipping
			// plane.
			#if UNITY_REVERSED_Z
				// Case for platforms with REVERSED_Z, such as D3D.
				if (depth < 0.00001)
					return float4(0,0,0,1);
			#else
				// Case for platforms without REVERSED_Z, such as OpenGL.
				if (depth > 0.99999)
					return float4(0,0,0,1);
			#endif

			// Reconstruct the view space OR world space positions.
			float3 worldPos = ComputeWorldSpacePosition(UV, depth, UNITY_MATRIX_I_VP);
			float3 camPos = ComputeViewSpacePosition(UV, depth, UNITY_MATRIX_I_VP);

			float depth01 = Linear01Depth(depth, _ZBufferParams);

			// Split the depth value digits across 4 channels, because converting a float (4 bytes) to uint8 (1 byte) loses data.
			float4 bitEncodings = float4(1.0, 255.0, 255.0*255.0, 255.0*255.0*255.0);
			float4 encodings = bitEncodings * depth01;
			encodings = frac(encodings);
			encodings -= encodings.yzww * float2(1./255., 0.).xxxy;

			return encodings;
		}
		ENDHLSL
		}
	}
}