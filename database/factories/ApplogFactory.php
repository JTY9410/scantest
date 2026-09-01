<?php

namespace Database\Factories;

use App\Models\Applog;
use App\Models\User;
use Illuminate\Database\Eloquent\Factories\Factory;

/**
 * @extends \Illuminate\Database\Eloquent\Factories\Factory<\App\Models\Applog>
 */
class ApplogFactory extends Factory
{
    protected $model = Applog::class;

    /**
     * Define the model's default state.
     *
     * @return array<string, mixed>
     */
    public function definition(): array
    {
        $types = ['error', 'warning', 'info', 'debug', 'critical'];
        $type = $this->faker->randomElement($types);

        $messages = [
            'error' => [
                '데이터베이스 연결 실패',
                'API 요청 타임아웃',
                '인증 토큰 만료',
                '잘못된 요청 형식',
                '서버 내부 오류',
            ],
            'warning' => [
                '메모리 사용량 높음',
                '디스크 공간 부족',
                '네트워크 지연 발생',
                '캐시 만료 임박',
                '백업 실패',
            ],
            'info' => [
                '사용자 로그인',
                '데이터 동기화 완료',
                '새로운 버전 배포',
                '시스템 점검 완료',
                '백업 시작',
            ],
            'debug' => [
                'API 요청 시작',
                '쿼리 실행 시간',
                '메모리 사용량',
                '캐시 히트율',
                '세션 상태',
            ],
            'critical' => [
                '시스템 다운',
                '데이터 손상 감지',
                '보안 위협 감지',
                '디스크 오류',
                '네트워크 연결 끊김',
            ],
        ];

        $user = User::inRandomOrder()->first();

        return [
            'timestamp' => $this->faker->dateTimeBetween('-1 month', 'now'),
            'user_id' => $user?->id,
            'user_tid' => $user?->tid,
            'type' => $type,
            'message' => $this->faker->randomElement($messages[$type]),
            'desc' => $this->faker->optional(0.7)->paragraph(),
        ];
    }
}
