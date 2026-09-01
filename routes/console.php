<?php

use Illuminate\Foundation\Inspiring;
use Illuminate\Support\Facades\Artisan;
use Illuminate\Support\Facades\Log;
use Illuminate\Support\Facades\Schedule;

Artisan::command('inspire', function () {
    $this->comment(Inspiring::quote());
})->purpose('Display an inspiring quote');


// 스케쥴러는 자동으로 코드 수정시 바로 적용 된다.

// 스케줄러 테스트 로그
// 등록 안됐을 경우 : docker compose exec app php artisan schedule:run
Schedule::call(function () {
    Log::info('스케줄러가 정상적으로 실행됨: ' . now() . ' (console.php)');
})
->name('scheduler-test')
->withoutOverlapping()
->everyMinute();
