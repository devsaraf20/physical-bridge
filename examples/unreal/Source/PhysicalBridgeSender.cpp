// PhysicalBridgeSender.cpp - see header for setup.
#include "PhysicalBridgeSender.h"

#include "Engine/TextureRenderTarget2D.h"
#include "OSCClient.h"
#include "OSCManager.h"
#include "OSCMessage.h"

UPhysicalBridgeSender::UPhysicalBridgeSender()
{
	PrimaryComponentTick.bCanEverTick = true;
}

void UPhysicalBridgeSender::BeginPlay()
{
	Super::BeginPlay();
	Client = UOSCManager::CreateOSCClient(Host, Port, TEXT("PhysicalBridge"), this);
}

static FOSCMessage MakeMessage(const FString& Stream)
{
	FOSCMessage Message;
	UOSCManager::SetOSCMessageAddress(Message, UOSCManager::ConvertStringToOSCAddress(TEXT("/pb/") + Stream));
	return Message;
}

void UPhysicalBridgeSender::SendValue(const FString& Stream, float Value)
{
	if (!Client) return;
	FOSCMessage Message = MakeMessage(Stream);
	UOSCManager::AddFloat(Message, Value);
	Client->SendOSCMessage(Message);
}

void UPhysicalBridgeSender::SendAngles(const FString& Stream, const TArray<float>& Angles)
{
	if (!Client || Angles.Num() == 0) return;
	FOSCMessage Message = MakeMessage(Stream);
	for (float Angle : Angles)
	{
		UOSCManager::AddFloat(Message, Angle);
	}
	Client->SendOSCMessage(Message);
}

void UPhysicalBridgeSender::SendGrid(const FString& Stream, int32 Width, int32 Height, const TArray<uint8>& Values)
{
	if (!Client || Width <= 0 || Height <= 0 || Values.Num() != Width * Height) return;
	FOSCMessage Message = MakeMessage(Stream);
	UOSCManager::AddInt32(Message, Width);
	UOSCManager::AddInt32(Message, Height);
	UOSCManager::AddBlob(Message, Values);
	Client->SendOSCMessage(Message);
}

void UPhysicalBridgeSender::SendRenderTarget(const FString& Stream, UTextureRenderTarget2D* RenderTarget)
{
	if (!RenderTarget) return;
	FTextureRenderTargetResource* Resource = RenderTarget->GameThread_GetRenderTargetResource();
	if (!Resource) return;
	TArray<FColor> Pixels;
	// Synchronous GPU readback: fine for tiny targets (<= 64x64), avoid for big ones.
	if (!Resource->ReadPixels(Pixels)) return;
	const int32 W = RenderTarget->SizeX, H = RenderTarget->SizeY;
	TArray<uint8> Luma;
	Luma.SetNumUninitialized(W * H);
	for (int32 i = 0; i < W * H && i < Pixels.Num(); ++i)
	{
		const FColor& C = Pixels[i];
		Luma[i] = static_cast<uint8>((C.R * 77 + C.G * 150 + C.B * 29) >> 8);
	}
	SendGrid(Stream, W, H, Luma);
}

void UPhysicalBridgeSender::TickComponent(float DeltaTime, ELevelTick TickType, FActorComponentTickFunction* ThisTickFunction)
{
	Super::TickComponent(DeltaTime, TickType, ThisTickFunction);
	Accumulator += DeltaTime;
	if (SendRateHz > 0.f && Accumulator < 1.f / SendRateHz) return;
	Accumulator = 0.f;

	if (AngleSources.Num() > 0)
	{
		TArray<float> Angles;
		for (const FComponentReference& Ref : AngleSources)
		{
			const USceneComponent* Comp = Cast<USceneComponent>(Ref.GetComponent(GetOwner()));
			if (!Comp) { Angles.Add(0.f); continue; }
			const FRotator R = Comp->GetRelativeRotation();
			Angles.Add(AngleAxis == 0 ? R.Roll : AngleAxis == 1 ? R.Pitch : R.Yaw);
		}
		SendAngles(AngleStream, Angles);
	}
	if (GridSource)
	{
		SendRenderTarget(GridStream, GridSource);
	}
}
