<?php

namespace App\Http\Middleware;

use Closure;
use Exception;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\Log;
use PHPOpenSourceSaver\JWTAuth\Facades\JWTAuth;
use PHPOpenSourceSaver\JWTAuth\Http\Middleware\BaseMiddleware;
use PHPOpenSourceSaver\JWTAuth\Exceptions\TokenExpiredException;
use PHPOpenSourceSaver\JWTAuth\Exceptions\TokenInvalidException;
use PHPOpenSourceSaver\JWTAuth\Exceptions\TokenBlacklistedException;
use PHPOpenSourceSaver\JWTAuth\Exceptions\JWTException;
use Symfony\Component\HttpFoundation\Response;
use App\Models\User;

class JwtMiddleware extends BaseMiddleware
{
    public function handle(Request $request, Closure $next): Response
    {
        // 1단계: JWT 토큰 인증 시도
        try {
            $user = JWTAuth::parseToken()->authenticate();

            if (!$user) {
                return response()->json([
                    'message' => '사용자를 찾을 수 없습니다.',
                ], 401);
            }

            // 토큰 버전 확인
            $token = JWTAuth::getToken();
            $payload = JWTAuth::getPayload($token);
            $tokenVersion = $payload->get('token_version', 1);

            Log::info('토큰 버전 확인', [
                'user_id' => $user->id,
                'token_version_from_payload' => $tokenVersion,
                'user_token_version' => $user->token_version,
            ]);

            if ($tokenVersion !== $user->token_version) {
                Log::warning('토큰 버전 불일치', [
                    'user_id' => $user->id,
                    'token_version_from_payload' => $tokenVersion,
                    'user_token_version' => $user->token_version,
                ]);

                return response()->json([
                    'message' => '토큰이 무효화되었습니다.',
                ], 401);
            }

            // JWT 인증 성공
            return $next($request);

        } catch (TokenExpiredException $e) {
            Log::warning('토큰 만료', [
                'error' => $e->getMessage(),
            ]);
            // JWT 실패 시 API 키 체크로 진행
        } catch (TokenInvalidException $e) {
            Log::warning('유효하지 않은 토큰', [
                'error' => $e->getMessage(),
            ]);
            // JWT 실패 시 API 키 체크로 진행
        } catch (TokenBlacklistedException $e) {
            Log::warning('블랙리스트에 등록된 토큰', [
                'error' => $e->getMessage(),
            ]);
            // JWT 실패 시 API 키 체크로 진행
        } catch (JWTException $e) {
            Log::warning('JWT 예외 발생', [
                'error' => $e->getMessage(),
            ]);
            // JWT 실패 시 API 키 체크로 진행
        }

        // 2단계: API 키 인증 시도
        $apiKey = $request->input('api_key');

        if ($apiKey) {
            $user = User::where('api_key', $apiKey)->first();

            if ($user) {
                // API 키 만료 확인
                if ($user->isApiKeyExpired()) {
                    Log::warning('API 키 만료', [
                        'user_id' => $user->id,
                        'expires_at' => $user->api_expires_at,
                    ]);
                    return response()->json([
                        'message' => 'API 키가 만료되었습니다.',
                    ], 401);
                }

                // IP 허용 여부 확인
                $clientIp = $request->ip();
                if (!$user->isIpAllowed($clientIp)) {
                    Log::warning('허용되지 않은 IP', [
                        'user_id' => $user->id,
                        'client_ip' => $clientIp,
                        'allowed_hosts' => $user->api_host,
                    ]);
                    return response()->json([
                        'message' => '허용되지 않은 IP 주소입니다.',
                    ], 403);
                }

                // API 키 인증 성공
                Log::info('API 키 인증 성공', [
                    'user_id' => $user->id,
                    'client_ip' => $clientIp,
                ]);

                auth()->setUser($user);
                return $next($request);
            }

            Log::warning('유효하지 않은 API 키', [
                'api_key_length' => strlen($apiKey),
            ]);
        }

        // 둘 다 실패
        return response()->json([
            'message' => '인증이 필요합니다.',
        ], 401);
    }
}
